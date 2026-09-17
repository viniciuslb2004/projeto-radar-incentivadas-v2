// Aba Tendencias & Insights: setores em alta/queda, subsetores, produtos, maiores operacoes.

let chartProdutos, chartSubsetores, chartSegmentos, chartIncentivadaEvolucao, chartEstruturaRanking;
let subsetorSelectInicializado = false;
let segmentoSelectInicializado = false;
let _ultimaEstruturaMercado = null; // cache da ultima /estrutura_mercado, reaproveitada pelo toggle sem refetch

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
// No modo Primario, indexador_padronizado tem cobertura real de só ~1,7%
// (medido ao vivo, 2026-09-17 -- ver CLAUDE.md, seção Frontend): a maioria
// das ofertas vem do rito automático/Resolução CVM 160, que NUNCA populate
// esse campo (ver "Segunda fonte CVM"). A resposta de
// `/tendencias/indexadores` inclui uma linha "Não informado" que sozinha
// somava ~98% do total -- deixar essa fatia no gráfico o tornava
// essencialmente ilegível (uma barra gigante + traços quase invisíveis).
// Reformulado (mantendo o endpoint como está): filtra "Não informado" do
// desenho e mostra a cobertura real como aviso explícito, mesmo padrão de
// #chart-taxas-aviso/#chart-prazos-aviso. No Incentivado, produto/instrumento
// tem cobertura tipicamente completa -- o aviso nunca aparece nesse caso.
async function loadProdutos(filters) {
  const endpoint = _mercadoAtivo === "primario" ? "/api/primario/tendencias/indexadores" : "/api/tendencias/produtos";
  const campo = _mercadoAtivo === "primario" ? "indexador" : "produto";
  const aviso = document.getElementById("chart-produtos-aviso");
  const vazio = document.getElementById("chart-produtos-vazio");
  let data;
  try {
    data = await fetchJSON(endpoint + "?" + qs(filters));
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];

  let linhas = data;
  if (_mercadoAtivo === "primario") {
    const naoInformado = data.find((d) => d[campo] === "Não informado");
    linhas = data.filter((d) => d[campo] !== "Não informado");
    if (aviso) {
      const totalOps = data.reduce((acc, d) => acc + (d.n_operacoes || 0), 0);
      const nInformado = totalOps - (naoInformado ? naoInformado.n_operacoes || 0 : 0);
      if (totalOps > 0) {
        const pct = ((nInformado / totalOps) * 100).toFixed(1).replace(".", ",");
        aviso.textContent = `⚠ Amostra parcial: indexador identificado em ${fmtNum(nInformado)} de ${fmtNum(totalOps)} operações (${pct}%) — a maior parte da atividade recente (2023+) vem do rito automático da CVM, que não registra esse campo.`;
        aviso.style.display = "block";
      } else {
        aviso.style.display = "none";
      }
    }
  } else if (aviso) {
    aviso.style.display = "none";
  }

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
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => fmtBRLFull(ctx.raw) } } },
      scales: { x: { ticks: { callback: (v) => fmtBRL(v) } } },
    },
  });
}

// ---- Evolução da participação Lei 12.431 (incentivada) -- novo, só Primário ----
// Complementa o donut "Estrutura da oferta" do Consolidado (composição
// ATUAL) com a dimensão de TEMPO -- ver CLAUDE.md, seção Frontend, redesenho
// 2026-09-17. Reaproveita `_sequenciaCompletaPeriodos`/`_rotuloPeriodoSerie`
// (definidas em consolidado.js, carregado ANTES deste arquivo -- ver
// <script> em index.html -- funções globais de script plano, não módulo).
// Granularidade fixa em trimestral (Tendências não tem seletor de
// granularidade próprio, diferente do Consolidado).
//
// Por que `incentivada` e não `indexador_padronizado`: uma primeira versão
// tentou uma série por indexador, mas medido ao vivo contra produção esse
// campo só vem do arquivo CVM principal, que praticamente para de
// contribuir linhas a partir de 2023 -- o gráfico cairia a zero justo nos
// anos mais recentes, sugerindo (de forma enganosa) que o mercado indexado
// tivesse sumido, quando é só um artefato de qual arquivo CVM cobre qual
// período (ver CLAUDE.md, seção "Segunda fonte CVM"). `incentivada` vem dos
// DOIS arquivos CVM, com cobertura real contínua 2010-2026.
async function loadIncentivadaEvolucao(filters) {
  if (_mercadoAtivo !== "primario") {
    if (chartIncentivadaEvolucao) { chartIncentivadaEvolucao.destroy(); chartIncentivadaEvolucao = null; }
    return;
  }
  let data;
  try {
    data = await fetchJSON("/api/primario/serie_temporal_incentivada?" + qs({ ...filters, granularidade: "trimestral" }));
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];
  const paresUnicos = [...new Map(data.map((d) => [`${d.ano}-${d.periodo}`, { ano: d.ano, periodo: d.periodo }])).values()];
  const periodos = _sequenciaCompletaPeriodos("trimestral", paresUnicos).map((s) => s.label);
  // Ordem fixa (nao alfabetica/descoberta) pra cor ficar estavel entre
  // filtros -- "Não informado" sempre por ultimo/cinza, nunca escondido
  // (mesmo espirito dos donuts de Incentivada/Regime fiduciario).
  const categorias = ["Sim", "Não", "Não informado"];
  const cores = { "Sim": AZUL_TONS[0], "Não": AZUL_TONS[4], "Não informado": "#D9D9D9" };
  const datasets = categorias
    .filter((cat) => data.some((d) => d.incentivada === cat))
    .map((cat) => ({
      label: cat,
      backgroundColor: cores[cat],
      data: periodos.map((p) => {
        const row = data.find((d) => _rotuloPeriodoSerie("trimestral", d.ano, d.periodo) === p && d.incentivada === cat);
        return row ? row.valor_total : 0;
      }),
    }));
  if (chartIncentivadaEvolucao) chartIncentivadaEvolucao.destroy();
  const canvas = document.getElementById("chart-incentivada-evolucao");
  if (!canvas) return;
  chartIncentivadaEvolucao = new Chart(canvas, {
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

// ---- Principais agentes fiduciários e custodiantes (novo, só Primário) ----
// "Quem estrutura as ofertas" -- dimensão de mercado de capitais sem
// equivalente nenhum no crédito de fomento (BNDES/FINEP não tem conceito de
// agente fiduciário/custodiante). Cobertura PARCIAL e conhecida (só linhas
// vindas do rito automático/Resolução CVM 160 têm esses campos, ver
// CLAUDE.md, seção Pipeline CVM) -- aviso sempre construído a partir da
// resposta real da API (nunca um número fixo), mesmo padrão de
// #chart-taxas-aviso/#chart-prazos-aviso no Consolidado. Os dois rankings
// (agente fiduciário / custodiante) vêm do MESMO fetch (`/estrutura_mercado`,
// que também alimenta os donuts de Incentivada/Regime fiduciário no
// Consolidado) -- o select troca só qual bloco é desenhado, sem refetch.
function _renderEstruturaRanking() {
  const select = document.getElementById("estrutura-dimensao-select");
  const aviso = document.getElementById("estrutura-ranking-aviso");
  const vazio = document.getElementById("estrutura-ranking-vazio");
  if (!select) return;
  const dimensao = select.value; // "agentes_fiduciarios" | "custodiantes"
  const bloco = _ultimaEstruturaMercado ? _ultimaEstruturaMercado[dimensao] : null;
  const linhas = bloco && Array.isArray(bloco.linhas) ? bloco.linhas : [];

  if (aviso) {
    if (bloco && typeof bloco.n_total === "number") {
      const rotulo = dimensao === "agentes_fiduciarios" ? "agente fiduciário" : "custodiante";
      const pct = bloco.cobertura_pct != null ? bloco.cobertura_pct.toFixed(1).replace(".", ",") : "0,0";
      aviso.textContent = `⚠ Amostra parcial: ${rotulo} identificado em ${fmtNum(bloco.n_com_dado)} de ${fmtNum(bloco.n_total)} operações (${pct}%) — só o rito automático (Resolução CVM 160) registra esse dado.`;
      aviso.style.display = "block";
    } else {
      aviso.style.display = "none";
    }
  }

  if (!linhas.length) {
    if (vazio) vazio.style.display = "block";
    if (chartEstruturaRanking) { chartEstruturaRanking.destroy(); chartEstruturaRanking = null; }
    return;
  }
  if (vazio) vazio.style.display = "none";

  if (chartEstruturaRanking) chartEstruturaRanking.destroy();
  const canvas = document.getElementById("chart-estrutura-ranking");
  if (!canvas) return;
  chartEstruturaRanking = new Chart(canvas, {
    type: "bar",
    data: {
      labels: linhas.map((l) => l.nome),
      datasets: [{ data: linhas.map((l) => l.valor_total), backgroundColor: AZUL_TONS[1] }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (ctx) => `${fmtBRLFull(ctx.raw)} (n=${fmtNum(linhas[ctx.dataIndex].n || 0)})` },
        },
      },
      scales: { x: { ticks: { callback: (v) => fmtBRL(v) } } },
    },
  });
}

async function loadEstruturaRanking(filters) {
  if (_mercadoAtivo !== "primario") {
    if (chartEstruturaRanking) { chartEstruturaRanking.destroy(); chartEstruturaRanking = null; }
    return;
  }
  try {
    _ultimaEstruturaMercado = await fetchJSON("/api/primario/estrutura_mercado?" + qs(filters));
  } catch (e) {
    _ultimaEstruturaMercado = null;
  }
  _renderEstruturaRanking();
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
    loadIncentivadaEvolucao(filters),
    loadEstruturaRanking(filters),
  ]);
  await popularSeletorSubsetor(setoresRanking, filters);
  await popularSeletorSegmento(setoresRanking);
  await Promise.all([loadSubsetores(filters), loadSegmentos(filters)]);
}

document.addEventListener("DOMContentLoaded", () => {
  onFiltersChange(refreshTendencias);
  document.getElementById("maiores-ordenar").addEventListener("change", () => loadMaioresOperacoes(currentFilters()));
  document.getElementById("maiores-exportar-btn").addEventListener("click", exportarMaioresOperacoesCSV);
  // Toggle Agente fiduciário / Custodiante -- reusa o MESMO fetch já feito
  // por loadEstruturaRanking (cache em _ultimaEstruturaMercado), nunca
  // refaz a chamada à API só por causa da troca de dimensão.
  const estruturaSelect = document.getElementById("estrutura-dimensao-select");
  if (estruturaSelect) estruturaSelect.addEventListener("change", _renderEstruturaRanking);
  // Espera o filterbar compartilhado (agencia/setor/UF/data -- ver common.js)
  // estar de fato pronto, incluindo os valores vindos de um link com filtro na
  // URL, antes do fetch inicial -- ver comentario de filtrosProntosPromise em
  // common.js sobre por que isso NAO pode ser so um setTimeout com prazo fixo.
  filtrosProntosPromise.then(() => refreshTendencias(currentFilters()));
});
