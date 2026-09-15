// Aba Editais: chamadas publicas ABERTAS da FINEP -- filtros, dashboard de prazos,
// lista ordenada por urgencia, detalhe do edital, e o endgame (descreva seu
// projeto -> quais editais parecem aplicaveis, por similaridade semantica).

const PUBLICO_LABELS = {
  empresa1: "Empresa (menor porte)",
  empresa2: "Empresa (porte médio-baixo)",
  empresa3: "Empresa (porte médio)",
  empresa4: "Empresa (porte médio-alto)",
  empresa5: "Empresa (grande porte)",
  ict: "ICT",
  startup: "Startup",
  cooperativa: "Cooperativa",
  fundos: "Fundos de investimento",
  produtorRural: "Produtor rural",
};

let chartEditaisTema;
let editaisAtuais = [];

function fmtDataCurta(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d)) return "-";
  return d.toLocaleDateString("pt-BR", { timeZone: "UTC" });
}

function prazoInfo(edital) {
  const dias = edital.dias_restantes;
  if (dias === null || dias === undefined) {
    return { classe: "sem-prazo", texto: "Sem prazo definido" };
  }
  if (dias < 0) return { classe: "sem-prazo", texto: "Prazo encerrado" };
  if (dias === 0) return { classe: "urgente", texto: "Encerra hoje" };
  if (dias <= 7) return { classe: "urgente", texto: `Faltam ${dias} dia${dias > 1 ? "s" : ""}` };
  if (dias <= 30) return { classe: "atencao", texto: `Faltam ${dias} dias` };
  return { classe: "tranquilo", texto: `Faltam ${dias} dias` };
}

function tagListHTML(chaves) {
  if (!chaves || !chaves.length) return "";
  return `<div class="tag-list">${chaves.map((c) => `<span class="tag">${PUBLICO_LABELS[c] || c}</span>`).join("")}</div>`;
}

function editalCardHTML(edital) {
  const prazo = prazoInfo(edital);
  return `<div class="edital-card" data-id="${edital.id}">
    <div class="top-row">
      <span class="edital-titulo">${edital.titulo || "-"}</span>
      <span class="prazo-badge ${prazo.classe}">${prazo.texto}</span>
    </div>
    <div class="meta">${edital.tema_principal || "Tema não classificado"}${edital.regiao ? " · " + edital.regiao : ""}${edital.tipo_oportunidade ? " · " + edital.tipo_oportunidade : ""}</div>
    ${tagListHTML(edital.publico_alvo)}
  </div>`;
}

function renderEditaisLista(lista) {
  const container = document.getElementById("editais-lista");
  document.getElementById("editais-lista-titulo").textContent = `Editais (${fmtNum(lista.length)})`;
  if (!lista.length) {
    container.innerHTML = '<p class="empty-state">Nenhum edital encontrado para esse filtro.</p>';
    return;
  }
  container.innerHTML = lista.map(editalCardHTML).join("");
  container.querySelectorAll(".edital-card").forEach((card) => {
    card.addEventListener("click", () => openEditalDetalhe(card.dataset.id));
  });
}

function currentEditaisFilters() {
  return {
    situacao: document.getElementById("ed-f-situacao").value,
    aplicavel_empresa: document.getElementById("ed-f-empresa").value,
    tema: document.getElementById("ed-f-tema").value,
    regiao: document.getElementById("ed-f-regiao").value,
    tipo_oportunidade: document.getElementById("ed-f-tipo").value,
    q: document.getElementById("ed-f-texto").value.trim(),
  };
}

// ============ Filtros na URL (ver secao "Filtros na URL" em common.js) ============
// ed-ordenar (ordenacao da lista) fica DE FORA de proposito -- mesma logica ja
// aplicada a granularidade do grafico de serie temporal em common.js: muda so
// como os mesmos dados sao exibidos, nao qual fatia deles aparece.
function _sincronizarFiltrosEditaisNaURL() {
  sincronizarFiltrosNaURL(currentEditaisFilters());
}

function _aplicarFiltrosEditaisDaURL() {
  const params = paramsDaURL();
  if (params.has("situacao")) document.getElementById("ed-f-situacao").value = params.get("situacao");
  if (params.has("aplicavel_empresa")) document.getElementById("ed-f-empresa").value = params.get("aplicavel_empresa");
  if (params.has("tema")) document.getElementById("ed-f-tema").value = params.get("tema");
  if (params.has("regiao")) document.getElementById("ed-f-regiao").value = params.get("regiao");
  if (params.has("tipo_oportunidade")) document.getElementById("ed-f-tipo").value = params.get("tipo_oportunidade");
  if (params.has("q")) document.getElementById("ed-f-texto").value = params.get("q");
}

async function loadEditaisFiltrosOpcoes() {
  const filtros = await fetchJSON("/api/editais/filtros");
  const fill = (id, values) => {
    const sel = document.getElementById(id);
    values.forEach((v) => sel.appendChild(new Option(v, v)));
  };
  fill("ed-f-tema", filtros.temas);
  fill("ed-f-regiao", filtros.regioes);
  fill("ed-f-tipo", filtros.tipos_oportunidade);
}

async function loadEditaisDashboard(filters) {
  const data = await fetchJSON("/api/editais/dashboard?" + qs(filters));
  document.getElementById("editais-kpi-row").innerHTML =
    kpiCard("Editais encontrados", fmtNum(data.n_total)) +
    kpiCard("Fecham em até 30 dias", fmtNum(data.n_fecham_30_dias), data.n_fecham_30_dias ? "atenção ao prazo" : "");

  const temas = data.por_tema.slice(0, 12);
  if (chartEditaisTema) chartEditaisTema.destroy();
  chartEditaisTema = new Chart(document.getElementById("chart-editais-tema"), {
    type: "bar",
    data: {
      labels: temas.map((t) => t.tema),
      datasets: [{ data: temas.map((t) => t.n_editais), backgroundColor: AZUL_TONS[1] }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      onClick: (evt, els) => {
        if (!els.length) return;
        const tema = temas[els[0].index].tema;
        if (tema === "Não classificado") return;
        document.getElementById("ed-f-tema").value = tema;
        _sincronizarFiltrosEditaisNaURL();
        refreshEditais();
      },
    },
  });
}

async function loadEditaisLista(filters) {
  const [order_by, order_dir] = document.getElementById("ed-ordenar").value.split("-");
  const data = await fetchJSON("/api/editais?" + qs(Object.assign({}, filters, { order_by, order_dir })));
  editaisAtuais = data;
  renderEditaisLista(data);
}

function exportarEditaisCSV() {
  exportarCSV("editais.csv", editaisAtuais, [
    { chave: "titulo", rotulo: "Título" },
    { chave: "situacao", rotulo: "Situação" },
    { chave: "tema_principal", rotulo: "Tema" },
    { chave: "tipo_oportunidade", rotulo: "Tipo de oportunidade" },
    { chave: "tipo_cooperacao", rotulo: "Tipo de cooperação" },
    { chave: "contrapartida", rotulo: "Contrapartida" },
    { chave: "regiao", rotulo: "Região" },
    { chave: "data_publicacao", rotulo: "Publicado em" },
    { chave: "prazo_proposto", rotulo: "Prazo de submissão" },
    { chave: "vigencia_fim", rotulo: "Vigência até" },
  ]);
}

async function refreshEditais() {
  const filters = currentEditaisFilters();
  await Promise.all([loadEditaisDashboard(filters), loadEditaisLista(filters)]);
}

// ============ Detalhe do edital (reaproveita o modal global) ============

function documentosHTML(documentos) {
  if (!documentos || !documentos.length) {
    return '<p class="empty-state" style="padding:12px 0;">Nenhum documento identificado automaticamente -- confira o edital completo no link acima.</p>';
  }
  return `<ul class="detalhe-doc-list">${documentos
    .map((d) => `<li><a href="${d.url}" target="_blank" rel="noopener">${d.label}</a></li>`)
    .join("")}</ul>`;
}

async function openEditalDetalhe(id) {
  document.getElementById("modal-title").textContent = "Detalhe do edital";
  document.getElementById("modal-ordenar").style.display = "none";
  document.getElementById("modal-favoritar-btn").style.display = "none";
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const edital = await fetchJSON(`/api/editais/${id}`);
  if (edital.erro) {
    body.innerHTML = `<p class="empty-state">${edital.erro}</p>`;
    return;
  }

  const prazo = prazoInfo(edital);
  const badgeSituacao = `<span class="badge ${edital.situacao === "aberta" ? "up" : "down"}" style="margin-left:8px;">${edital.situacao === "aberta" ? "Aberto" : "Encerrado"}</span>`;
  document.getElementById("modal-title").innerHTML = `${edital.titulo} ${badgeSituacao}`;

  const corPrazo = prazo.classe === "urgente" ? "aprovacao-indisponivel" : prazo.classe === "sem-prazo" ? "aprovacao-indisponivel" : "aprovacao-disponivel";

  let html = `<div class="detalhe-secoes">`;
  html += `<div class="detalhe-prazo-box ${corPrazo}">
    <div style="font-size:20px; font-weight:800; white-space:nowrap;">${prazo.texto}</div>
    <div style="font-size:12px; color:var(--text-muted);">Prazo de submissão: ${fmtDataCurta(edital.prazo_proposto)}${edital.vigencia_fim ? " · Vigência até: " + fmtDataCurta(edital.vigencia_fim) : ""}</div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Quem pode se candidatar</div>
    <div style="padding:14px;">${tagListHTML(edital.publico_alvo) || '<span class="empty-state" style="padding:0;">Público-alvo não detalhado nos metadados.</span>'}</div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Informações gerais</div>
    <div class="detalhe-grid">
      <div class="detalhe-campo"><div class="detalhe-label">Tema</div><div class="detalhe-valor">${edital.tema_principal || "-"}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Tipo de oportunidade</div><div class="detalhe-valor">${edital.tipo_oportunidade || "-"}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Tipo de cooperação</div><div class="detalhe-valor">${edital.tipo_cooperacao || "-"}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Contrapartida</div><div class="detalhe-valor">${edital.contrapartida || "-"}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Região</div><div class="detalhe-valor">${edital.regiao || "-"}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Publicado em</div><div class="detalhe-valor">${fmtDataCurta(edital.data_publicacao)}</div></div>
    </div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Descrição completa</div>
    <div class="detalhe-texto-longo">${(edital.descricao_texto || "Sem descrição disponível.").trim()}</div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Documentos</div>
    <div style="padding: 0 14px 14px;">${documentosHTML(edital.documentos)}</div>
  </div>`;

  html += `</div>`;
  body.innerHTML = html;
}

// ============ Endgame: descreva seu projeto -> editais aderentes ============
// Busca por similaridade semantica (embeddings) dos editais abertos contra a
// descricao do projeto/empresa.

async function runEditaisEndgame(q) {
  const container = document.getElementById("editais-endgame-resultado");
  container.innerHTML = '<p class="empty-state">Buscando editais aderentes...</p>';

  // Modo hospedado calcula o vetor da descricao NO NAVEGADOR (transformers.js, ver
  // embeddings-client.js, unico jeito de nao estourar os 512MB de RAM do free tier
  // do servidor) e manda pronto; modo local (desktop) continua igual a sempre
  // (get_model() no proprio backend).
  let buscaResp;
  try {
    if (window.MODO_HOSPEDADO) {
      const vetor = await embutirQuery(q, (info) => {
        if (info && info.status === "progress" && typeof info.progress === "number") {
          container.innerHTML = `<p class="empty-state">Baixando modelo de busca no seu navegador (${Math.round(info.progress)}%)...</p>`;
        }
      });
      buscaResp = await postJSON("/api/editais/buscar", { q, vetor }, 60000);
    } else {
      buscaResp = await fetchJSON("/api/editais/buscar?" + qs({ q }), 60000);
    }
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao buscar. Tente novamente.</p>';
    return;
  }
  if (buscaResp.erro) {
    container.innerHTML = `<p class="empty-state">${buscaResp.erro}</p>`;
    return;
  }

  const resultados = buscaResp.resultados || [];
  if (!resultados.length) {
    container.innerHTML = '<p class="empty-state">Nenhum edital aberto parece aderente a essa descrição.</p>';
    return;
  }

  let html = "";
  if (buscaResp.confianca_baixa) {
    html += '<div class="confianca-baixa-aviso">⚠ Não encontramos uma correspondência forte para essa descrição -- os editais abaixo são os mais próximos disponíveis, mas com similaridade baixa.</div>';
  }
  html += '<div id="editais-endgame-lista"></div>';
  container.innerHTML = html;

  const lista = document.getElementById("editais-endgame-lista");
  lista.innerHTML = resultados.map(editalCardHTML).join("");
  lista.querySelectorAll(".edital-card").forEach((card) => {
    card.addEventListener("click", () => openEditalDetalhe(card.dataset.id));
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadEditaisFiltrosOpcoes();

  // Link compartilhado/F5: aplica os filtros da URL so depois das opcoes de
  // tema/regiao/tipo estarem populadas acima, e so quando a aba ativa na URL e
  // de fato Editais (ver _viewInicialDaURL).
  if (_viewInicialDaURL() === "editais") _aplicarFiltrosEditaisDaURL();

  ["ed-f-situacao", "ed-f-empresa", "ed-f-tema", "ed-f-regiao", "ed-f-tipo"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      _sincronizarFiltrosEditaisNaURL();
      refreshEditais();
    });
  });
  document.getElementById("ed-f-texto").addEventListener(
    "input",
    debounce(_sincronizarFiltrosEditaisNaURL, 400)
  );
  document.getElementById("ed-f-texto").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      _sincronizarFiltrosEditaisNaURL();
      refreshEditais();
    }
  });
  document.getElementById("ed-ordenar").addEventListener("change", refreshEditais);
  document.getElementById("editais-exportar-btn").addEventListener("click", exportarEditaisCSV);

  const endgameInput = document.getElementById("ed-endgame-input");
  document.getElementById("ed-endgame-btn").addEventListener("click", () => {
    if (endgameInput.value.trim().length >= 5) runEditaisEndgame(endgameInput.value.trim());
  });
  endgameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && endgameInput.value.trim().length >= 5) runEditaisEndgame(endgameInput.value.trim());
  });

  refreshEditais();
});
