// Aba Consolidado: KPIs + serie temporal + setores + UF + porte.

let chartSerie, chartSetores, chartUF, chartPorte;

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

async function loadUF(filters) {
  const data = (await fetchJSON("/api/uf?" + qs(filters))).slice(0, 12);
  if (chartUF) chartUF.destroy();
  chartUF = new Chart(document.getElementById("chart-uf"), {
    type: "bar",
    data: {
      labels: data.map((d) => d.uf),
      datasets: [{ data: data.map((d) => d.valor_total), backgroundColor: AZUL_TONS[2] }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => fmtBRLFull(ctx.raw) } } },
      scales: { y: { ticks: { callback: (v) => fmtBRL(v) } } },
      onClick: (evt, els) => {
        if (!els.length) return;
        const uf = data[els[0].index].uf;
        openOperacoesModal(`UF: ${uf}`, { uf });
      },
    },
  });
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
