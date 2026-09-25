// Aba Consolidado: KPIs + serie temporal + setores + UF + porte.

let chartSerie, chartSetores, chartPorte;

function kpiCard(label, value, sub) {
  // Tudo aqui e texto puro (rotulos + valores formatados) -- escapado por seguranca.
  return `<div class="kpi-card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>`;
}

async function loadKPIs(filters, token) {
  let data;
  try {
    data = await fetchJSON("/api/kpis?" + qs(filters));
  } catch (e) {
    if (token !== undefined && token !== _consolidadoToken) return;
    document.getElementById("kpi-row").innerHTML = htmlErroCarga();
    return;
  }
  if (token !== undefined && token !== _consolidadoToken) return;
  const porAgencia = (data.por_agencia || []).map((a) => `${a.agencia}: ${fmtBRL(a.valor_total)}`).join(" · ");
  document.getElementById("kpi-row").innerHTML =
    kpiCard("Nº de operações", fmtNum(data.n_operacoes)) +
    kpiCard("Volume contratado", fmtBRL(data.valor_contratado_total), porAgencia) +
    kpiCard("Volume desembolsado/pago", fmtBRL(data.valor_desembolsado_total)) +
    kpiCard("Cheque médio", fmtBRL(data.cheque_medio));
}

// Item 4 (pedido 2026-09-23): o ano corrente (2026) ainda esta em andamento -- a base
// so tem dado ate o mes mais recente realmente refletido no ultimo refresh, nunca o
// ano completo. Na granularidade "anual" isso faz o ultimo rotulo ("2026") parecer um
// total do ano inteiro quando na verdade e parcial -- sem indicacao, um leitor
// compararia 2026 contra 2025 (ano completo) como se fossem periodos do mesmo
// tamanho. Descobre o mes/ano mais recente com dado REAL (MAX(data_contratacao) via
// /api/filtros, ja cacheado por _fetchFiltrosCompartilhado em common.js -- nao bate
// rede de novo) em vez de hardcodar o ano corrente ou o mes atual do relogio (a base
// pode estar atrasada em relacao a hoje por dias/semanas ate o proximo refresh
// semanal rodar).
let _anoMesMaxCache = null;
async function _carregarAnoMesMax() {
  if (_anoMesMaxCache) return _anoMesMaxCache;
  try {
    const filtros = await _fetchFiltrosCompartilhado();
    if (filtros && filtros.data_max) {
      const dt = new Date(filtros.data_max);
      if (!isNaN(dt)) _anoMesMaxCache = { ano: dt.getUTCFullYear(), mes: dt.getUTCMonth() + 1 };
    }
  } catch (e) {
    // sem indicacao de YTD se o fetch falhar -- rotulo cai no caso normal (sem sufixo).
  }
  return _anoMesMaxCache;
}

// Rotulo do eixo X por granularidade -- sempre zero-padded pra ordenacao lexica
// (string sort) bater com a ordenacao cronologica em todos os 4 casos.
// anoMesMax (opcional): {ano, mes} do dado mais recente da base -- so aplica o
// sufixo "(YTD)" na granularidade "anual" (rotulo hoje literalmente so "2026", sem
// nenhum outro sinal de que e parcial -- trimestral/mensal/semestral ja mostram o
// recorte especifico dentro do ano, nao reivindicam ser o ano inteiro).
function _rotuloPeriodoSerie(granularidade, ano, periodo, anoMesMax) {
  if (granularidade === "mensal") return `${ano}-${String(periodo).padStart(2, "0")}`;
  if (granularidade === "semestral") return `${ano}-S${periodo}`;
  if (granularidade === "anual") return `${ano}`; // sufixo YTD virou nota abaixo do grafico + tooltip
  return `${ano}-T${periodo}`; // trimestral (padrao)
}

// true se o periodo (ano/granularidade) e o ultimo ano da serie e esta parcial
// (dado so vai ate anoMesMax.mes, nao o ano inteiro) -- usado pra tooltip.
function _periodoParcial(granularidade, ano, anoMesMax) {
  return granularidade === "anual" && anoMesMax && ano === anoMesMax.ano && anoMesMax.mes < 12;
}

const _PASSOS_POR_ANO = { mensal: 12, trimestral: 4, semestral: 2, anual: 1 };

// Preenche periodos SEM nenhuma operacao (de nenhuma agência) como zero, em vez de
// simplesmente omitir esse ponto do eixo X -- so faz sentido pra metricas aditivas
// (valor_total, n_operacoes: "zero operacoes" e um fato real, nao um dado inventado),
// e so preenche o MEIO do intervalo observado (do primeiro ao ultimo periodo com
// algum dado), nunca estende pra alem do que a base realmente cobre.
function _sequenciaCompletaPeriodos(granularidade, pares, anoMesMax) {
  if (!pares.length) return [];
  const passos = _PASSOS_POR_ANO[granularidade] || 4;
  const indice = ({ ano, periodo }) => ano * passos + (periodo - 1);
  const min = Math.min(...pares.map(indice));
  const max = Math.max(...pares.map(indice));
  const seq = [];
  for (let i = min; i <= max; i++) {
    const ano = Math.floor(i / passos);
    const periodo = (i % passos) + 1;
    seq.push({ ano, periodo, label: _rotuloPeriodoSerie(granularidade, ano, periodo, anoMesMax) });
  }
  return seq;
}

async function loadSerieTemporal(filters) {
  const granularidade = document.getElementById("serie-granularidade").value;
  const reqId = (loadSerieTemporal._id = (loadSerieTemporal._id || 0) + 1);
  let data, anoMesMax;
  try {
    [data, anoMesMax] = await Promise.all([
      fetchJSON("/api/serie_temporal?" + qs({ ...filters, granularidade })),
      _carregarAnoMesMax(),
    ]);
  } catch (e) {
    data = null;
  }
  if (reqId !== loadSerieTemporal._id) return; // resposta antiga (filtro/granularidade mudou)
  if (!Array.isArray(data)) { if (chartSerie) { chartSerie.destroy(); chartSerie = null; } return; }
  const agrupador = "agencia";
  const paresUnicos = [...new Map(data.map((d) => [`${d.ano}-${d.periodo}`, { ano: d.ano, periodo: d.periodo }])).values()];
  const periodos = _sequenciaCompletaPeriodos(granularidade, paresUnicos, anoMesMax).map((s) => s.label);
  const grupos = [...new Set(data.map((d) => d[agrupador]))];
  const coresIncentivado = { BNDES: "#223850", FINEP: "#5878A0", BNB: "#A9BAC9" };

  const datasets = grupos.map((g) => ({
    label: g,
    backgroundColor: coresIncentivado[g] || "#5878A0",
    data: periodos.map((p) => {
      const row = data.find((d) => _rotuloPeriodoSerie(granularidade, d.ano, d.periodo, anoMesMax) === p && d[agrupador] === g);
      return row ? row.valor_total : 0;
    }),
  }));

  const sequencia = _sequenciaCompletaPeriodos(granularidade, paresUnicos, anoMesMax);
  const anoDoIndice = (i) => (sequencia[i] ? sequencia[i].ano : null);

  // Nota "Dados até <mês>/<ano>" abaixo do grafico -- mesma fonte (anoMesMax) que
  // antes alimentava o sufixo "(YTD)" no rotulo do eixo X. So exibe se a serie
  // realmente alcanca o ano/mes mais recente (senao a nota nao se aplicaria ao
  // recorte de filtro atual).
  const elDadosAte = document.getElementById("chart-serie-dados-ate");
  if (elDadosAte) {
    const mostrar = anoMesMax && sequencia.some((s) => s.ano === anoMesMax.ano);
    elDadosAte.textContent = mostrar ? `Dados até ${MESES[anoMesMax.mes - 1]}/${anoMesMax.ano}` : "";
  }

  if (chartSerie) chartSerie.destroy();
  chartSerie = new Chart(document.getElementById("chart-serie"), {
    type: "bar",
    data: { labels: periodos, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => fmtBRL(v) } } },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${fmtBRLFull(ctx.raw)}`,
            afterLabel: (ctx) => {
              const ano = anoDoIndice(ctx.dataIndex);
              return _periodoParcial(granularidade, ano, anoMesMax) ? `(até ${MESES[anoMesMax.mes - 1]}/${ano})` : undefined;
            },
          },
        },
      },
    },
  });
}

// Ranking por setor_bndes (CNAE).
async function loadSetores(filters) {
  let data;
  try {
    data = await fetchJSON("/api/setores?" + qs(filters));
    data = Array.isArray(data) ? data.slice(0, 10) : [];
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];
  const campo = "setor";
  if (chartSetores) chartSetores.destroy();
  chartSetores = new Chart(document.getElementById("chart-setores"), {
    type: "bar",
    data: {
      labels: data.map((d) => d[campo]),
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
        const valor = data[els[0].index][campo];
        openOperacoesModal(`Setor: ${valor}`, { setor: valor });
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
    tooltip.innerHTML = `<strong>${esc(NOME_UF[uf] || uf)}</strong><br><span class="valor">${esc(valorHtml)}</span>`;
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
  // ?v=2: viewBox reduzido 10x (stroke-width do style.css acompanha) -- bust do
  // cache de 1 dia de /img/* (vercel.json) pra nao misturar SVG velho + CSS novo.
  _ufMapSvgPromise = fetch("/img/brasil-uf.svg?v=2")
    .then((r) => {
      if (!r.ok) throw new Error("svg indisponivel");
      return r.text();
    })
    .then((svgText) => {
      container.innerHTML = svgText; // asset estatico proprio, nao dado da API
      container.dataset.carregado = "1";
      _ligarEventosMapaUF(container);
    })
    .catch(() => {
      _ufMapSvgPromise = null; // tenta de novo no proximo refresh
      container.innerHTML = htmlErroCarga("Não foi possível carregar o mapa agora.");
    });
  return _ufMapSvgPromise;
}

async function loadUF(filters) {
  let data;
  try {
    data = await fetchJSON("/api/uf?" + qs(filters));
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];

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
      const somaValor = foraDoMapa.reduce((acc, d) => acc + (d.valor_total || 0), 0);
      const somaOps = foraDoMapa.reduce((acc, d) => acc + (d.n_operacoes || 0), 0);
      foraEl.textContent =
        `+ ${fmtBRL(somaValor)} (${fmtNum(somaOps)} operações) de abrangência nacional/interestadual ` +
        "ou sem UF informada.";
    } else {
      foraEl.textContent = "";
    }
  }
}

async function loadPorte(filters) {
  let data;
  try {
    data = await fetchJSON("/api/porte?" + qs(filters));
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];
  if (chartPorte) chartPorte.destroy();
  chartPorte = new Chart(document.getElementById("chart-porte"), {
    type: "doughnut",
    data: {
      labels: data.map((d) => d.porte),
      datasets: [{ data: data.map((d) => d.valor_total), backgroundColor: data.map((d) => CORES_PORTE[d.porte] || AZUL_TONS[5]) }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${fmtBRLFull(ctx.raw)}` } } },
      onClick: (evt, els) => {
        if (!els.length) return;
        const porte = data[els[0].index].porte;
        openOperacoesModal(`Porte: ${porte}`, { porte });
      },
    },
  });
}

// ---- Cascata Setor -> Subsetor (#f-setor -> #f-subsetor, filterbar compartilhado
// com Tendencias, ver docs/frontend-abas.md) ----
// Escolher um Setor restringe as opcoes de #f-subsetor as daquele setor (via
// /api/subsetores?setor=X, que ja existe e ja e usado em Tendencias pro drill-down).
// Quando o Setor muda pra um que nao contem mais o subsetor selecionado, o subsetor
// e resetado pra "Todos" -- nunca deixa um par Setor/Subsetor incompativel aplicado
// em silencio (ex: Setor=Comercio e Servicos + Subsetor=Industria de Base nao existe).
// Exposta como window.aoMudarSetorFiltro -- chamada por common.js (listener
// generico de #f-setor) ANTES de notifyFiltersChange/sincronizarFiltrosNaURL, pra
// garantir que #f-subsetor.value ja esteja coerente antes dos graficos recarregarem
// (ver comentario em common.js sobre a ordem dos listeners).
async function _repopularSubsetorCascata(preservarValorAtual) {
  const setorSel = document.getElementById("f-setor");
  const subsetorSel = document.getElementById("f-subsetor");
  if (!setorSel || !subsetorSel) return;
  const setor = setorSel.value;
  const valorAnterior = subsetorSel.value;

  let subsetores;
  if (!setor || setor === "Todos") {
    // Sem setor escolhido: volta pra lista completa (todos os subsetores, de
    // qualquer setor) -- mesma fonte usada na populacao inicial do filterbar
    // (_fetchFiltrosCompartilhado ja cacheia a promise, entao isso nao bate rede
    // de novo depois da carga inicial).
    let filtros;
    try {
      filtros = await _fetchFiltrosCompartilhado();
    } catch (e) {
      filtros = {};
    }
    subsetores = (filtros.subsetores || []).filter(Boolean);
  } else {
    let data;
    try {
      data = await fetchJSON("/api/subsetores?setor=" + encodeURIComponent(setor));
    } catch (e) {
      data = [];
    }
    if (!Array.isArray(data)) data = [];
    subsetores = data.map((d) => d.subsetor).filter((s) => s && s !== "Não classificado");
  }

  _preencherSelectFiltro("f-subsetor", subsetores);
  subsetorSel.value = (preservarValorAtual && subsetores.includes(valorAnterior)) ? valorAnterior : "Todos";
}

window.aoMudarSetorFiltro = () => _repopularSubsetorCascata(false);

let _consolidadoToken = 0;
async function refreshConsolidado(filters) {
  filters = filters || currentFilters();
  const token = ++_consolidadoToken;
  await Promise.all([
    loadKPIs(filters, token),
    loadSerieTemporal(filters),
    loadSetores(filters),
    loadUF(filters),
    loadPorte(filters),
  ]);
}

document.addEventListener("DOMContentLoaded", async () => {
  const granularidadeSelect = document.getElementById("serie-granularidade");
  granularidadeSelect.addEventListener("change", () => {
    loadSerieTemporal(currentFilters());
  });
  await initFiltersAndTabs();
  // Narrowa #f-subsetor pro setor ja resolvido nesse ponto (default "Todos", ou
  // restaurado de um link com filtro na URL -- ver common.js) -- preserva o valor
  // de subsetor ja setado quando ele for compativel (caso de link direto), so
  // reseta se nao for (link com par Setor/Subsetor incompativel).
  await _repopularSubsetorCascata(true);
  onFiltersChange(refreshConsolidado);
  refreshConsolidado(currentFilters());
});
