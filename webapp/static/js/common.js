// Utilidades compartilhadas: filtros, formatacao, tabs, modal de drill-down.

const AZUL_TONS = ["#223850", "#2E4A68", "#36587E", "#5878A0", "#7C93AC", "#A9BAC9", "#D3DCE3"];

function fmtBRL(v) {
  if (v === null || v === undefined || isNaN(v)) return "-";
  if (Math.abs(v) >= 1e9) return "R$ " + (v / 1e9).toFixed(1).replace(".", ",") + " bi";
  if (Math.abs(v) >= 1e6) return "R$ " + (v / 1e6).toFixed(1).replace(".", ",") + " mi";
  if (Math.abs(v) >= 1e3) return "R$ " + (v / 1e3).toFixed(0) + " mil";
  return "R$ " + Math.round(v);
}

function fmtBRLFull(v) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

function fmtNum(v) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR");
}

// Quando o frontend e o backend estao hospedados em dominios separados (ex:
// frontend na Vercel, backend no Render), API_BASE_URL (definida em config.js)
// aponta pro backend; localmente fica "" (mesma origem, como sempre).
function _urlCompleta(url) {
  if (url.startsWith("/api/") && window.API_BASE_URL) {
    return window.API_BASE_URL.replace(/\/$/, "") + url;
  }
  return url;
}

async function fetchJSON(url, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  if (!timeoutMs) {
    const r = await fetch(fullUrl, { credentials: "include" });
    return r.json();
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const r = await fetch(fullUrl, { signal: controller.signal, credentials: "include" });
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// Usado para mandar de volta pro servidor um resultado gerado pela IA local do
// visitante (ex: resumo de edital), pra virar cache compartilhado com todo mundo.
async function postJSON(url, body, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const r = await fetch(fullUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "include",
      signal: controller ? controller.signal : undefined,
    });
    return await r.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

const MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

function currentFilters() {
  const filters = {
    agencia: document.getElementById("f-agencia").value,
    setor: document.getElementById("f-setor").value,
    uf: document.getElementById("f-uf").value,
  };

  const mesIni = document.getElementById("f-mes-ini").value;
  const anoIni = document.getElementById("f-ano-ini").value;
  if (mesIni && anoIni) {
    filters.data_inicio = `${anoIni}-${String(mesIni).padStart(2, "0")}-01`;
  }

  const mesFim = document.getElementById("f-mes-fim").value;
  const anoFim = document.getElementById("f-ano-fim").value;
  if (mesFim && anoFim) {
    let m = parseInt(mesFim, 10) + 1;
    let y = parseInt(anoFim, 10);
    if (m > 12) { m = 1; y += 1; }
    filters.data_fim = `${y}-${String(m).padStart(2, "0")}-01`;
  }

  return filters;
}

function qs(params) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "Todas" && v !== "Todos") p.set(k, v);
  });
  return p.toString();
}

const FILTER_LISTENERS = [];
function onFiltersChange(fn) { FILTER_LISTENERS.push(fn); }
function notifyFiltersChange() { FILTER_LISTENERS.forEach((fn) => fn(currentFilters())); }

async function initFiltersAndTabs() {
  const status = await fetchJSON("/api/status");
  window.MODO_HOSPEDADO = !!status.hospedado;
  document.dispatchEvent(new CustomEvent("modo-hospedado-conhecido"));
  const pill = document.getElementById("status-pill");
  if (status.ultimo_refresh && status.ultimo_refresh.finished_at) {
    const d = new Date(status.ultimo_refresh.finished_at);
    pill.textContent = `${fmtNum(status.n_operacoes)} operações · atualizado em ${d.toLocaleDateString("pt-BR")}`;
  } else {
    pill.textContent = `${fmtNum(status.n_operacoes)} operações`;
  }

  const filtros = await fetchJSON("/api/filtros");
  const fill = (id, values) => {
    const sel = document.getElementById(id);
    values.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
  };
  fill("f-agencia", filtros.agencias);
  fill("f-setor", filtros.setores.filter(Boolean));
  fill("f-uf", filtros.ufs.filter(Boolean));

  const anos = filtros.anos.filter((a) => a !== null).sort((a, b) => a - b);
  const anoIni = document.getElementById("f-ano-ini");
  const anoFim = document.getElementById("f-ano-fim");
  const mesIni = document.getElementById("f-mes-ini");
  const mesFim = document.getElementById("f-mes-fim");

  MESES.forEach((nome, i) => {
    mesIni.appendChild(new Option(nome, i + 1));
    mesFim.appendChild(new Option(nome, i + 1));
  });
  anos.forEach((a) => {
    anoIni.appendChild(new Option(a, a));
    anoFim.appendChild(new Option(a, a));
  });

  const dataMin = filtros.data_min ? new Date(filtros.data_min) : null;
  const dataMax = filtros.data_max ? new Date(filtros.data_max) : null;
  if (dataMin) {
    mesIni.value = dataMin.getUTCMonth() + 1;
    anoIni.value = dataMin.getUTCFullYear();
  } else if (anos.length) {
    anoIni.value = anos[0];
  }
  if (dataMax) {
    mesFim.value = dataMax.getUTCMonth() + 1;
    anoFim.value = dataMax.getUTCFullYear();
  } else if (anos.length) {
    anoFim.value = anos[anos.length - 1];
  }

  ["f-agencia", "f-setor", "f-uf", "f-mes-ini", "f-ano-ini", "f-mes-fim", "f-ano-fim"].forEach((id) => {
    document.getElementById(id).addEventListener("change", notifyFiltersChange);
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("view-" + btn.dataset.view).classList.add("active");
      document.getElementById("filterbar").style.display = (btn.dataset.view === "busca" || btn.dataset.view === "editais") ? "none" : "flex";
    });
  });
}

// ============ Modal de drill-down ============
const modalOverlay = () => document.getElementById("modal-overlay");

function closeModal() {
  modalOverlay().classList.remove("open");
}

let modalExtraFilters = {};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("modal-close").addEventListener("click", closeModal);
  modalOverlay().addEventListener("click", (e) => {
    if (e.target === modalOverlay()) closeModal();
  });
  document.getElementById("modal-ordenar").addEventListener("change", () => {
    openOperacoesModal(document.getElementById("modal-title").textContent, modalExtraFilters, true);
  });
});

async function openOperacoesModal(title, extraFilters, manterOrdenacao) {
  if (!manterOrdenacao) modalExtraFilters = extraFilters || {};
  document.getElementById("modal-title").textContent = title;
  const body = document.getElementById("modal-body");
  const ordenarSelect = document.getElementById("modal-ordenar");
  ordenarSelect.style.display = "inline-block";
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const [order_by, order_dir] = ordenarSelect.value.split("-");
  const params = Object.assign(currentFilters(), modalExtraFilters, { order_by, order_dir });
  const ops = await fetchJSON("/api/operacoes?" + qs(params) + "&limit=300");

  if (!ops.length) {
    body.innerHTML = '<p class="empty-state">Nenhuma operação encontrada para esse filtro.</p>';
    return;
  }

  let html = '<table class="ops-table"><thead><tr>' +
    "<th>Cliente</th><th>Agência</th><th>UF</th><th>Setor</th><th>Data</th><th>Valor contratado</th>" +
    "</tr></thead><tbody>";
  ops.forEach((op) => {
    html += `<tr data-id="${op.id}">
      <td>${op.cliente || "-"}</td>
      <td>${op.agencia}</td>
      <td>${op.uf || "-"}</td>
      <td>${op.setor_bndes || "Não classificado"}</td>
      <td>${op.data_contratacao || "-"}</td>
      <td>${fmtBRLFull(op.valor_contratado)}</td>
    </tr>`;
  });
  html += "</tbody></table>";
  body.innerHTML = html;

  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
}

function fmtCampoDetalhe(campo) {
  const v = campo.valor;
  switch (campo.tipo) {
    case "moeda":
      return fmtBRLFull(v);
    case "percentual":
      return `${Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
    case "meses":
      return `${v} meses`;
    case "dias":
      return `${v} dias`;
    case "data":
      return v;
    default:
      return String(v).trim();
  }
}

async function openOperacaoDetalhe(id) {
  document.getElementById("modal-title").textContent = "Detalhe da operação";
  document.getElementById("modal-ordenar").style.display = "none";
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const data = await fetchJSON(`/api/operacoes/${id}`);
  if (!data.secoes || !data.secoes.length) {
    body.innerHTML = '<p class="empty-state">Detalhe não encontrado.</p>';
    return;
  }

  const badge = `<span class="badge" style="background:var(--blue-lightest); color:var(--navy); margin-left:8px;">${data.agencia}${data.instrumento ? " · " + data.instrumento : ""}</span>`;
  document.getElementById("modal-title").innerHTML = `Detalhe da operação ${badge}`;

  let html = '<div class="detalhe-secoes">';
  data.secoes.forEach((secao) => {
    const textoLongo = secao.campos.find((c) => c.tipo === "texto_longo");
    const camposCurtos = secao.campos.filter((c) => c.tipo !== "texto_longo");

    html += `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">${secao.titulo}</div>`;

    if (camposCurtos.length) {
      html += '<div class="detalhe-grid">';
      camposCurtos.forEach((c) => {
        html += `<div class="detalhe-campo">
          <div class="detalhe-label">${c.label}</div>
          <div class="detalhe-valor">${fmtCampoDetalhe(c)}</div>
        </div>`;
      });
      html += "</div>";
    }
    if (textoLongo) {
      html += `<div class="detalhe-texto-longo">${fmtCampoDetalhe(textoLongo)}</div>`;
    }
    html += "</div>";
  });
  html += "</div>";
  body.innerHTML = html;
}
