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

// Sem ISSO por padrao, uma chamada sem timeoutMs explicito nunca resolvia nem
// rejeitava se o backend travasse/nao respondesse (ex: cold-start do free tier do
// Render meio truncado por algum motivo) -- o await ficava pendurado pra sempre.
// Isso ja travou a pagina inteira de verdade: initFiltersAndTabs() (ver mais
// abaixo) so registra os cliques das abas DEPOIS do fetch de /api/status, entao um
// fetch sem timeout que nunca resolve deixa ate a NAVEGACAO entre abas travada,
// nao so o dado que ficaria faltando. 45s cobre com folga o cold-start do Render;
// chamadas que legitimamente demoram mais ja passam o proprio timeoutMs mais longo
// explicitamente, entao nao sao afetadas.
const TIMEOUT_PADRAO_MS = 45000;

// ============ Login (tela custom, ver #login-overlay em index.html) ============
// As rotas /api/* continuam exigindo HTTP Basic por baixo dos panos (ver
// webapp/main.py::_verificar_acesso), mas o HTML/CSS/JS estatico virou publico --
// em vez do navegador mostrar o dialogo NATIVO feio de usuario/senha (que so
// dispara em navegacao de pagina inteira, nunca em fetch()), a propria pagina
// carrega e testa as credenciais via fetch() contra /api/status. O header
// "Authorization: Basic ..." fica guardado em sessionStorage (some ao fechar a
// aba -- "temporario" por design, mesmo padrao ja usado pro historico de busca).
const AUTH_HEADER_KEY = "radar_auth_header";

function _getAuthHeader() {
  try { return sessionStorage.getItem(AUTH_HEADER_KEY) || null; } catch (e) { return null; }
}
function _setAuthHeader(header) {
  try { sessionStorage.setItem(AUTH_HEADER_KEY, header); } catch (e) { /* sem storage -- login nao persiste entre reloads, mas continua funcionando na mesma pagina */ }
}

class ErroAutenticacao extends Error {}

async function fetchJSON(url, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  const headers = {};
  const auth = _getAuthHeader();
  if (auth) headers["Authorization"] = auth;
  try {
    const r = await fetch(fullUrl, { signal: controller.signal, credentials: "include", headers });
    if (r.status === 401) throw new ErroAutenticacao("nao autenticado");
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// POST generico (usado, por exemplo, para mandar ao servidor o vetor de embedding
// ja calculado no navegador, no modo hospedado -- ver embeddings-client.js).
async function postJSON(url, body, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  const headers = { "Content-Type": "application/json" };
  const auth = _getAuthHeader();
  if (auth) headers["Authorization"] = auth;
  try {
    const r = await fetch(fullUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "include",
      signal: controller.signal,
    });
    if (r.status === 401) throw new ErroAutenticacao("nao autenticado");
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

function _mostrarLoginOverlay(mensagemErro) {
  document.getElementById("login-overlay").classList.remove("hidden");
  const erro = document.getElementById("login-erro");
  if (mensagemErro) {
    erro.textContent = mensagemErro;
    erro.classList.remove("hidden");
  } else {
    erro.classList.add("hidden");
  }
  document.getElementById("login-usuario").focus();
}

// Testa as credenciais digitadas direto (nao via fetchJSON, que usaria o header ja
// GUARDADO em vez do candidato que ainda nem foi validado) -- so guarda de verdade
// se /api/status responder 200.
async function _tentarLogin(usuario, senha) {
  const header = "Basic " + btoa(usuario + ":" + senha);
  try {
    const r = await fetch(_urlCompleta("/api/status"), { headers: { Authorization: header }, credentials: "include" });
    if (r.status === 200) {
      _setAuthHeader(header);
      return true;
    }
  } catch (e) {
    // erro de rede tratado como falha de login tambem -- usuario ve a mesma
    // mensagem e pode tentar de novo.
  }
  return false;
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("login-card").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("login-btn");
    btn.disabled = true;
    btn.textContent = "Entrando...";
    const usuario = document.getElementById("login-usuario").value;
    const senha = document.getElementById("login-senha").value;
    const ok = await _tentarLogin(usuario, senha);
    btn.disabled = false;
    btn.textContent = "Entrar";
    if (ok) {
      // Recarrega a pagina inteira em vez de tentar re-disparar manualmente a
      // inicializacao de cada aba (consolidado.js, tendencias.js etc, cada um so
      // roda seu proprio DOMContentLoaded uma vez) -- mais simples e robusto:
      // com o header ja guardado, o proximo /api/status já passa direto.
      location.reload();
    } else {
      document.getElementById("login-senha").value = "";
      _mostrarLoginOverlay("Usuário ou senha incorretos.");
    }
  });
});

// Exporta uma lista de objetos como CSV (abre direto no Excel/Sheets) -- so client-side,
// sem ida ao servidor, pra funcionar igual no modo local e no hospedado. `colunas` e uma
// lista de {chave, rotulo}; `rotulo` vira o cabecalho, `chave` busca o valor em cada linha
// (aceita "a.b" para acessar aninhado, embora nenhum uso atual precise disso).
function exportarCSV(nomeArquivo, linhas, colunas) {
  const escapar = (valor) => {
    if (valor === null || valor === undefined) return "";
    const texto = String(valor);
    return /[",\n;]/.test(texto) ? '"' + texto.replace(/"/g, '""') + '"' : texto;
  };
  const cabecalho = colunas.map((c) => escapar(c.rotulo)).join(";");
  const corpo = linhas
    .map((linha) => colunas.map((c) => escapar(linha[c.chave])).join(";"))
    .join("\n");
  // BOM (﻿) pra o Excel abrir os acentos certo em UTF-8 sem precisar importar manualmente.
  const blob = new Blob(["﻿" + cabecalho + "\n" + corpo], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nomeArquivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
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

// Roteamento por caminho: a URL reflete APENAS qual aba esta aberta (/consolidado,
// /tendencias, /busca, /editais, /linhas-incentivadas), nunca estado de filtro/select
// (ex: granularidade do grafico) -- isso fica so na pagina (estado de sessao, se perde
// ao recarregar), pedido explicito do usuario pra manter a barra de endereco limpa.
const _SLUG_PARA_VIEW = {
  "": "consolidado",
  "consolidado": "consolidado",
  "tendencias": "tendencias",
  "busca": "busca",
  "editais": "editais",
  "linhas-incentivadas": "linhas",
};
const _VIEW_PARA_SLUG = {
  consolidado: "consolidado",
  tendencias: "tendencias",
  busca: "busca",
  editais: "editais",
  linhas: "linhas-incentivadas",
};

function _viewInicialDaURL() {
  const slug = window.location.pathname.replace(/^\/+|\/+$/g, "");
  return _SLUG_PARA_VIEW[slug] || "consolidado";
}

function _ativarView(view, empilharHistorico) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  document.getElementById("filterbar").style.display =
    view === "busca" || view === "editais" || view === "linhas" ? "none" : "flex";
  const caminho = "/" + (_VIEW_PARA_SLUG[view] || "consolidado");
  if (window.location.pathname !== caminho) {
    if (empilharHistorico) window.history.pushState({ view }, "", caminho);
    else window.history.replaceState({ view }, "", caminho);
  }
}

// Nao deixa o usuario chegar num intervalo invertido (De > Ate): sempre que um dos 4
// selects de data muda, compara os dois pares como "ano*12+mes" (comparavel direto,
// sem precisar montar Date) -- se o par que NAO acabou de mudar ficou invalido em
// relacao ao que mudou, ajusta ele pra igualar o que o usuario acabou de escolher
// (em vez de reverter a escolha do usuario ou so avisar sem corrigir). O aviso
// inline (#filtro-data-aviso, mesmo padrao visual de .confianca-baixa-aviso usado na
// busca) aparece por alguns segundos so quando uma correcao de verdade acontece.
function _ordemMesAno(mes, ano) {
  if (!mes || !ano) return null;
  return parseInt(ano, 10) * 12 + parseInt(mes, 10);
}

function validarIntervaloDatas(campoAlterado) {
  const mesIniEl = document.getElementById("f-mes-ini");
  const anoIniEl = document.getElementById("f-ano-ini");
  const mesFimEl = document.getElementById("f-mes-fim");
  const anoFimEl = document.getElementById("f-ano-fim");

  const ordemIni = _ordemMesAno(mesIniEl.value, anoIniEl.value);
  const ordemFim = _ordemMesAno(mesFimEl.value, anoFimEl.value);
  if (ordemIni === null || ordemFim === null || ordemIni <= ordemFim) return;

  // O campo que acabou de mudar manda -- o outro lado e que se ajusta pra igualar.
  const alterouInicio = campoAlterado === "f-mes-ini" || campoAlterado === "f-ano-ini";
  if (alterouInicio) {
    mesFimEl.value = mesIniEl.value;
    anoFimEl.value = anoIniEl.value;
  } else {
    mesIniEl.value = mesFimEl.value;
    anoIniEl.value = anoFimEl.value;
  }

  const aviso = document.getElementById("filtro-data-aviso");
  if (aviso) {
    aviso.style.display = "block";
    clearTimeout(aviso._timeoutId);
    aviso._timeoutId = setTimeout(() => { aviso.style.display = "none"; }, 4000);
  }
}

function _ligarBotoesDeAba() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => _ativarView(btn.dataset.view, true));
  });
  window.addEventListener("popstate", () => _ativarView(_viewInicialDaURL(), false));
  _ativarView(_viewInicialDaURL(), false);
}

// Esconde a tela de carregamento inicial -- chamada em TODO caminho de saida de
// initFiltersAndTabs() (sucesso ou erro), pra nunca deixar o usuario preso atras
// dela se o backend estiver fora do ar.
function _esconderLoadingOverlay() {
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.classList.add("hidden");
}

async function initFiltersAndTabs() {
  // Troca de aba e 100% client-side (so classes CSS) -- liga ISSO primeiro e
  // incondicionalmente, antes de qualquer fetch, pra a navegacao nunca depender
  // do backend responder.
  _ligarBotoesDeAba();

  const pill = document.getElementById("status-pill");
  let status;
  try {
    status = await fetchJSON("/api/status");
  } catch (e) {
    _esconderLoadingOverlay();
    if (e instanceof ErroAutenticacao) {
      _mostrarLoginOverlay();
      return;
    }
    pill.textContent = "não foi possível conectar ao servidor";
    return;
  }
  window.MODO_HOSPEDADO = !!status.hospedado;
  window.BUSCA_IA_ATIVA = !!status.busca_ia_ativa;
  document.dispatchEvent(new CustomEvent("modo-hospedado-conhecido"));
  if (status.ultimo_refresh && status.ultimo_refresh.finished_at) {
    const d = new Date(status.ultimo_refresh.finished_at);
    pill.textContent = `${fmtNum(status.n_operacoes)} operações · atualizado em ${d.toLocaleDateString("pt-BR")}`;
  } else {
    pill.textContent = `${fmtNum(status.n_operacoes)} operações`;
  }

  let filtros;
  try {
    filtros = await fetchJSON("/api/filtros");
  } catch (e) {
    _esconderLoadingOverlay();
    return;
  }
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

  const CAMPOS_DATA = ["f-mes-ini", "f-ano-ini", "f-mes-fim", "f-ano-fim"];
  ["f-agencia", "f-setor", "f-uf", ...CAMPOS_DATA].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      if (CAMPOS_DATA.includes(id)) validarIntervaloDatas(id);
      notifyFiltersChange();
    });
  });

  _esconderLoadingOverlay();
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

  // Integracao transacoes <-> linhas incentivadas (item 8): mesma logica do lado
  // inverso em linhas.js -- so setor_bndes (taxonomia nativa das 4 categorias),
  // rotulado "potencialmente compativel", nunca misturado com o detalhe da operacao.
  if (data.setor_bndes && typeof fetchJSON === "function") {
    try {
      const linhas = await fetchJSON("/api/linhas?" + qs({ setor: data.setor_bndes, limit: 3 }));
      if (linhas.resultados && linhas.resultados.length) {
        const div = document.createElement("div");
        div.className = "detalhe-secao";
        div.innerHTML = `<div class="detalhe-secao-titulo">Linhas incentivadas potencialmente compatíveis <span class="hint">mesmo setor -- não é confirmação de elegibilidade</span></div>` +
          '<ul class="clickable-list">' +
          linhas.resultados.map((l) => `<li data-linha-id="${l.id}"><span>${l.nome_simplificado || l.nome_oficial}</span><span class="badge neutro">${l.instituicao}</span></li>`).join("") +
          "</ul>";
        body.appendChild(div);
        div.querySelectorAll("li[data-linha-id]").forEach((li) => {
          li.addEventListener("click", () => {
            if (typeof openLinhaDetalhe === "function") openLinhaDetalhe(li.dataset.linhaId);
          });
        });
      }
    } catch (e) {
      // integracao e um extra -- se falhar, so nao mostra a secao.
    }
  }
}
