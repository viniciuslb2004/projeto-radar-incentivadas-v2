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
  return `<div class="tag-list">${chaves.map((c) => `<span class="tag">${esc(PUBLICO_LABELS[c] || c)}</span>`).join("")}</div>`;
}

// Item 8 (pedido 2026-09-23): card e a apresentacao PRINCIPAL de um edital (a maioria
// dos temas tem so 1 edital aberto por vez -- um grafico de contagem por tema virava
// uma parede de barras de tamanho 1, pouco informativo, ver loadEditaisDashboard).
// Enriquecido com instituicao (sempre FINEP -- unica fonte de editais_raw, ver
// CLAUDE.md/docs/modelo-dados-pipeline.md) + status Aberto/Encerrado explicito (MESMA
// logica ja usada no modal de detalhe, edital.situacao direto, ver openEditalDetalhe)
// + datas de abertura/fechamento reais (data_publicacao/prazo_proposto/vigencia_fim,
// todas ja vem do /api/editais, sem chamada nova). NAO mostra valor: editais_raw nao
// tem nenhum campo monetario (a FINEP nao publica valor de dotacao por chamada nos
// metadados que capturamos) -- omitido de proposito em vez de inventado.
function editalStatusBadgeHTML(edital) {
  const aberto = edital.situacao === "aberta";
  return `<span class="badge ${aberto ? "up" : "down"}">${aberto ? "Aberto" : "Encerrado"}</span>`;
}

function editalDatasHTML(edital) {
  const abertura = edital.data_publicacao ? `Publicado em ${fmtDataCurta(edital.data_publicacao)}` : null;
  const fechamento = edital.prazo_proposto
    ? `Encerra em ${fmtDataCurta(edital.prazo_proposto)}`
    : edital.vigencia_fim
    ? `Vigência até ${fmtDataCurta(edital.vigencia_fim)}`
    : null;
  const partes = [abertura, fechamento].filter(Boolean);
  return partes.length ? `<div class="meta" style="margin-top:4px;">${partes.join(" · ")}</div>` : "";
}

function editalCardHTML(edital) {
  const prazo = prazoInfo(edital);
  return `<div class="edital-card" data-id="${esc(edital.id)}">
    <div class="top-row">
      <span class="edital-titulo">${esc(edital.titulo || "-")}</span>
      <span class="prazo-badge ${prazo.classe}">${prazo.texto}</span>
    </div>
    <div class="meta">
      <span class="tag" style="margin-right:6px;">FINEP</span>${editalStatusBadgeHTML(edital)}
      ${edital.tema_principal ? " · " + esc(edital.tema_principal) : " · Tema não classificado"}${edital.regiao ? " · " + esc(edital.regiao) : ""}${edital.tipo_oportunidade ? " · " + esc(edital.tipo_oportunidade) : ""}
    </div>
    ${editalDatasHTML(edital)}
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
  let filtros;
  try {
    filtros = await fetchJSON("/api/editais/filtros");
  } catch (e) {
    return; // selects ficam so com "Todos" -- a aba continua usavel
  }
  const fill = (id, values) => {
    const sel = document.getElementById(id);
    (values || []).forEach((v) => sel.appendChild(new Option(v, v)));
  };
  fill("ed-f-tema", filtros.temas);
  fill("ed-f-regiao", filtros.regioes);
  fill("ed-f-tipo", filtros.tipos_oportunidade);
}

// Item 8: troca o grafico de barras "editais por tema" por uma lista de chips
// clicaveis (tema + contagem) -- com a maioria dos temas tendo so 1 edital aberto por
// vez, um bar chart virava uma parede de barras identicas de tamanho 1 (pouco
// informativo, dificil de escanear); chips com o numero embutido no rotulo
// aproveitam melhor o espaco pra contagens baixas/quase uniformes. Reaproveita o
// MESMO <canvas id="chart-editais-tema"> do HTML como ponto de montagem (substituido
// em runtime, nunca editado no arquivo estatico -- mesmo padrao ja usado por
// consolidado.js::_garantirDomMapaUF pro mapa de UF) -- so roda de verdade na 1a
// chamada, depois disso o canvas nao existe mais no DOM.
let _editaisTemasChipsPreparado = false;
function _garantirDomTemasEditais() {
  if (_editaisTemasChipsPreparado) return;
  const canvas = document.getElementById("chart-editais-tema");
  if (!canvas) return;
  const wrap = canvas.closest(".chart-wrap") || canvas.parentElement;
  // .chart-wrap tem altura fixa (280px, ver style.css) pensada pro <canvas> do
  // Chart.js -- removida aqui (so via JS, nao mexe no arquivo de estilo) pra uma
  // lista de chips nao deixar uma caixa vazia gigante embaixo dos chips.
  wrap.classList.remove("chart-wrap");
  wrap.style.minHeight = "0";
  wrap.innerHTML = '<div id="editais-temas-chips" class="tag-list" style="margin-top:2px;"></div>';
  _editaisTemasChipsPreparado = true;
}

async function loadEditaisDashboard(filters, token) {
  let data;
  try {
    data = await fetchJSON("/api/editais/dashboard?" + qs(filters));
  } catch (e) {
    if (token !== _editaisToken) return;
    document.getElementById("editais-kpi-row").innerHTML = "";
    return;
  }
  if (token !== _editaisToken) return;
  document.getElementById("editais-kpi-row").innerHTML =
    kpiCard("Editais encontrados", fmtNum(data.n_total)) +
    kpiCard("Fecham em até 30 dias", fmtNum(data.n_fecham_30_dias), data.n_fecham_30_dias ? "atenção ao prazo" : "");

  _garantirDomTemasEditais();
  const container = document.getElementById("editais-temas-chips");
  if (container) {
    const temas = (data.por_tema || []).filter((t) => t.tema && t.tema !== "Não classificado").slice(0, 20);
    container.innerHTML = temas.length
      ? temas
          .map((t) => `<span class="tag tema-chip" data-tema="${esc(t.tema)}" style="cursor:pointer;">${esc(t.tema)} (${esc(t.n_editais)})</span>`)
          .join("")
      : '<span class="empty-state" style="padding:0;">Nenhum tema classificado para este filtro.</span>';
    container.querySelectorAll(".tema-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        document.getElementById("ed-f-tema").value = chip.dataset.tema;
        _sincronizarFiltrosEditaisNaURL();
        refreshEditais();
      });
    });
  }
}

async function loadEditaisLista(filters, token) {
  const [order_by, order_dir] = document.getElementById("ed-ordenar").value.split("-");
  const container = document.getElementById("editais-lista");
  container.innerHTML = '<p class="empty-state">Carregando...</p>';
  let data;
  try {
    data = await fetchJSON("/api/editais?" + qs(Object.assign({}, filters, { order_by, order_dir })));
  } catch (e) {
    if (token !== _editaisToken) return;
    container.innerHTML = htmlErroCarga("Não foi possível carregar os editais agora. Tente novamente em instantes.");
    return;
  }
  if (token !== _editaisToken) return; // resposta de um filtro antigo
  editaisAtuais = Array.isArray(data) ? data : [];
  renderEditaisLista(editaisAtuais);
}

// Descarta respostas de chamadas antigas (troca rapida de filtro).
let _editaisToken = 0;
async function refreshEditais() {
  const filters = currentEditaisFilters();
  const token = ++_editaisToken;
  await Promise.all([loadEditaisDashboard(filters, token), loadEditaisLista(filters, token)]);
}

// ============ Detalhe do edital (reaproveita o modal global) ============

function documentosHTML(documentos) {
  if (!documentos || !documentos.length) {
    return '<p class="empty-state" style="padding:12px 0;">Nenhum documento identificado automaticamente -- confira o edital completo no link acima.</p>';
  }
  return `<ul class="detalhe-doc-list">${documentos
    .map((d) => `<li><a href="${escUrl(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.label || d.url)}</a></li>`)
    .join("")}</ul>`;
}

async function openEditalDetalhe(id) {
  document.getElementById("modal-title").textContent = "Detalhe do edital";
  document.getElementById("modal-ordenar").style.display = "none";
  document.getElementById("modal-copiar-link-btn").style.display = "none";
  document.getElementById("modal-favoritar-btn").classList.add("hidden");
  document.getElementById("modal-nota-container").classList.add("hidden");
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  let edital;
  try {
    edital = await fetchJSON(`/api/editais/${encodeURIComponent(id)}`);
  } catch (e) {
    body.innerHTML = htmlErroCarga("Não foi possível carregar este edital agora. Tente novamente em instantes.");
    return;
  }
  if (!edital || edital.erro) {
    body.innerHTML = `<p class="empty-state">${esc((edital && edital.erro) || "Edital não encontrado.")}</p>`;
    return;
  }

  const prazo = prazoInfo(edital);
  const badgeSituacao = `<span class="badge ${edital.situacao === "aberta" ? "up" : "down"}" style="margin-left:8px;">${edital.situacao === "aberta" ? "Aberto" : "Encerrado"}</span>`;
  document.getElementById("modal-title").innerHTML = `${esc(edital.titulo || "Edital")} ${badgeSituacao}`;

  const corPrazo = prazo.classe === "urgente" ? "aprovacao-indisponivel" : prazo.classe === "sem-prazo" ? "aprovacao-indisponivel" : "aprovacao-disponivel";

  let html = `<div class="detalhe-secoes">`;
  html += `<div class="detalhe-prazo-box ${corPrazo}">
    <div class="prazo-num">${prazo.texto}</div>
    <div class="prazo-sub">Prazo de submissão: ${fmtDataCurta(edital.prazo_proposto)}${edital.vigencia_fim ? " · Vigência até: " + fmtDataCurta(edital.vigencia_fim) : ""}</div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Quem pode se candidatar</div>
    <div style="padding:14px;">${tagListHTML(edital.publico_alvo) || '<span class="empty-state" style="padding:0;">Público-alvo não detalhado nos metadados.</span>'}</div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Informações gerais</div>
    <div class="detalhe-grid">
      <div class="detalhe-campo"><div class="detalhe-label">Tema</div><div class="detalhe-valor">${esc(edital.tema_principal || "-")}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Tipo de oportunidade</div><div class="detalhe-valor">${esc(edital.tipo_oportunidade || "-")}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Tipo de cooperação</div><div class="detalhe-valor">${esc(edital.tipo_cooperacao || "-")}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Contrapartida</div><div class="detalhe-valor">${esc(edital.contrapartida || "-")}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Região</div><div class="detalhe-valor">${esc(edital.regiao || "-")}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Publicado em</div><div class="detalhe-valor">${fmtDataCurta(edital.data_publicacao)}</div></div>
    </div>
  </div>`;

  html += `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Descrição completa</div>
    <div class="detalhe-texto-longo">${esc(String(edital.descricao_texto || "Sem descrição disponível.").trim())}</div>
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
  if (!buscaResp || buscaResp.erro) {
    container.innerHTML = `<p class="empty-state">${esc((buscaResp && buscaResp.erro) || "Erro ao buscar. Tente novamente.")}</p>`;
    return;
  }

  const resultados = buscaResp.resultados || [];
  if (!resultados.length) {
    container.innerHTML = '<p class="empty-state">Nenhum edital aberto parece aderente a essa descrição.</p>';
    return;
  }

  let html = "";
  if (buscaResp.confianca_baixa) {
    html += '<div class="confianca-baixa-aviso">Não encontramos uma correspondência forte para essa descrição -- os editais abaixo são os mais próximos disponíveis, mas com similaridade baixa.</div>';
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
    debounce(() => {
      _sincronizarFiltrosEditaisNaURL();
      refreshEditais();
    }, 300)
  );
  document.getElementById("ed-f-texto").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      _sincronizarFiltrosEditaisNaURL();
      refreshEditais();
    }
  });
  document.getElementById("ed-ordenar").addEventListener("change", refreshEditais);

  const endgameInput = document.getElementById("ed-endgame-input");
  document.getElementById("ed-endgame-btn").addEventListener("click", () => {
    if (endgameInput.value.trim().length >= 5) runEditaisEndgame(endgameInput.value.trim());
  });
  endgameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && endgameInput.value.trim().length >= 5) runEditaisEndgame(endgameInput.value.trim());
  });

  refreshEditais();
});
