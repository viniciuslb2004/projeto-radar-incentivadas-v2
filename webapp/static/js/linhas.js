// Aba Linhas Incentivadas: catalogo de linhas/programas de credito do BNDES, FINEP,
// Desenvolve SP e BNB (ver src/linhas_incentivadas.py) -- so consulta dados ja
// enriquecidos localmente, nunca acessa os sites das instituicoes em tempo real.

const LINHAS_PAGE_SIZE = 12;
let linhasPaginaAtual = 0;
let linhasFiltrosInicializados = false;

function currentLinhasFilters() {
  return {
    instituicao: document.getElementById("ln-f-instituicao").value,
    setor: document.getElementById("ln-f-setor").value,
    porte: document.getElementById("ln-f-porte").value,
    regiao: document.getElementById("ln-f-regiao").value,
    status: document.getElementById("ln-f-status").value,
    fluxo: document.getElementById("ln-f-fluxo").value,
    q: document.getElementById("linhas-busca-input").value.trim(),
  };
}

async function initLinhasFiltros() {
  if (linhasFiltrosInicializados) return;
  const filtros = await fetchJSON("/api/linhas/filtros");
  const fill = (id, values) => {
    const sel = document.getElementById(id);
    values.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
  };
  fill("ln-f-instituicao", filtros.instituicoes);
  fill("ln-f-setor", filtros.setores);
  fill("ln-f-porte", filtros.portes);
  fill("ln-f-regiao", filtros.regioes);
  fill("ln-f-status", filtros.status);
  fill("ln-f-fluxo", filtros.fluxos);
  linhasFiltrosInicializados = true;
}

function fmtValorLinha(min, max) {
  if (!min && !max) return null;
  if (min && max) return `${fmtBRL(min)} a ${fmtBRL(max)}`;
  if (min) return `a partir de ${fmtBRL(min)}`;
  return `até ${fmtBRL(max)}`;
}

function linhaCard(l) {
  const valor = fmtValorLinha(l.valor_minimo, l.valor_maximo);
  const atualizado = l.data_atualizacao ? new Date(l.data_atualizacao).toLocaleDateString("pt-BR") : "-";
  return `<div class="result-card" data-id="${l.id}">
    <div class="top-row">
      <span class="cliente">${l.nome_simplificado || l.nome_oficial}</span>
      <span class="badge neutro">${l.instituicao}</span>
    </div>
    <div class="meta">${l.setor_padronizado || "Setor não classificado"}${l.porte_padronizado ? " · " + l.porte_padronizado : ""}${l.regiao_elegivel ? " · " + l.regiao_elegivel : ""} · ${l.status || "Não informado pela fonte"}</div>
    <div class="meta">${l.descricao_resumida ? l.descricao_resumida.slice(0, 180) : ""}</div>
    <div class="meta">${valor ? valor + " · " : ""}${l.taxa_completa && l.taxa_completa !== "Não informado pela fonte" ? l.taxa_completa : ""}</div>
    <div class="score">Atualizado em ${atualizado} · <a href="${l.url_oficial}" target="_blank" rel="noopener" onclick="event.stopPropagation()">fonte oficial ↗</a></div>
  </div>`;
}

async function loadLinhas(pagina) {
  linhasPaginaAtual = pagina || 0;
  const container = document.getElementById("linhas-lista");
  container.innerHTML = '<p class="empty-state">Carregando linhas incentivadas...</p>';

  const filters = currentLinhasFilters();
  const [order_by, order_dir] = document.getElementById("linhas-ordenar").value.split("-");
  const offset = linhasPaginaAtual * LINHAS_PAGE_SIZE;

  let data;
  try {
    data = await fetchJSON("/api/linhas?" + qs({ ...filters, order_by, order_dir, limit: LINHAS_PAGE_SIZE, offset }));
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao carregar linhas incentivadas. Tente novamente.</p>';
    document.getElementById("linhas-contagem").textContent = "";
    document.getElementById("linhas-paginacao").innerHTML = "";
    return;
  }

  document.getElementById("linhas-contagem").textContent = `${fmtNum(data.total)} linha(s) incentivada(s) encontrada(s)`;

  if (!data.resultados.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma linha incentivada encontrada para esses filtros.</p>';
    document.getElementById("linhas-paginacao").innerHTML = "";
    return;
  }

  container.innerHTML = data.resultados.map(linhaCard).join("");
  container.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", () => openLinhaDetalhe(card.dataset.id));
  });

  const totalPaginas = Math.max(1, Math.ceil(data.total / LINHAS_PAGE_SIZE));
  const pagContainer = document.getElementById("linhas-paginacao");
  if (totalPaginas <= 1) {
    pagContainer.innerHTML = "";
  } else {
    pagContainer.innerHTML = `
      <button class="acao-btn" id="linhas-pag-anterior" ${linhasPaginaAtual === 0 ? "disabled" : ""}>‹ Anterior</button>
      <span class="progress-label" style="align-self:center;">Página ${linhasPaginaAtual + 1} de ${totalPaginas}</span>
      <button class="acao-btn" id="linhas-pag-proxima" ${linhasPaginaAtual + 1 >= totalPaginas ? "disabled" : ""}>Próxima ›</button>
    `;
    const btnAnt = document.getElementById("linhas-pag-anterior");
    const btnProx = document.getElementById("linhas-pag-proxima");
    if (btnAnt) btnAnt.addEventListener("click", () => loadLinhas(linhasPaginaAtual - 1));
    if (btnProx) btnProx.addEventListener("click", () => loadLinhas(linhasPaginaAtual + 1));
  }
}

function _campoDetalhe(rotulo, valor) {
  if (valor === null || valor === undefined || valor === "") return "";
  return `<div class="meta" style="margin-top:6px;"><strong>${rotulo}:</strong> ${valor}</div>`;
}

async function openLinhaDetalhe(id) {
  document.getElementById("modal-title").textContent = "Linha incentivada";
  const ordenarSelect = document.getElementById("modal-ordenar");
  ordenarSelect.style.display = "none";
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const l = await fetchJSON(`/api/linhas/${id}`);
  if (l.erro) {
    body.innerHTML = `<p class="empty-state">${l.erro}</p>`;
    return;
  }
  document.getElementById("modal-title").textContent = l.nome_oficial;

  body.innerHTML = `
    <div class="meta"><span class="badge neutro">${l.instituicao}</span> · ${l.status || "Não informado pela fonte"} · ${l.fluxo === "edital" ? "Edital/chamada pública" : "Fluxo contínuo"}</div>
    ${_campoDetalhe("Descrição", l.descricao_completa)}
    ${_campoDetalhe("Público-alvo / critérios de elegibilidade", l.criterios_elegibilidade)}
    ${_campoDetalhe("Setores elegíveis", l.setores_elegiveis)}
    ${_campoDetalhe("Setores não elegíveis", l.setores_nao_elegiveis)}
    ${_campoDetalhe("Porte elegível", l.porte_padronizado)}
    ${_campoDetalhe("Faixa de receita", l.faixa_receita)}
    ${_campoDetalhe("Região elegível", l.regiao_elegivel)}
    ${_campoDetalhe("Destinação", l.destinacao)}
    ${_campoDetalhe("Itens financiáveis", l.itens_financiaveis)}
    ${_campoDetalhe("Itens não financiáveis", l.itens_nao_financiaveis)}
    ${_campoDetalhe("Valor financiável", fmtValorLinha(l.valor_minimo, l.valor_maximo))}
    ${_campoDetalhe("Percentual financiável", l.percentual_financiavel)}
    ${_campoDetalhe("Contrapartida", l.contrapartida)}
    ${_campoDetalhe("Taxa completa", l.taxa_completa)}
    ${_campoDetalhe("Indexador", l.indexador)}
    ${_campoDetalhe("Spread", l.spread)}
    ${_campoDetalhe("Prazo total", l.prazo_total)}
    ${_campoDetalhe("Carência", l.carencia)}
    ${_campoDetalhe("Amortização", l.amortizacao)}
    ${_campoDetalhe("Garantias", l.garantias)}
    ${_campoDetalhe("Restrições", l.restricoes)}
    ${_campoDetalhe("Agente financeiro", l.agente_financeiro)}
    ${_campoDetalhe("Canal de contratação", l.canal_contratacao)}
    ${_campoDetalhe("Prazo de inscrição", l.prazo_inscricao)}
    ${_campoDetalhe("Documentos necessários", l.documentos_necessarios)}
    ${_campoDetalhe("Data de vigência", l.data_vigencia)}
    ${_campoDetalhe("Capturado em", l.data_captura ? new Date(l.data_captura).toLocaleDateString("pt-BR") : null)}
    ${_campoDetalhe("Atualizado em", l.data_atualizacao ? new Date(l.data_atualizacao).toLocaleDateString("pt-BR") : null)}
    ${_campoDetalhe("Origem do dado", l.origem_dado === "curadoria_manual_verificada" ? "Curadoria manual verificada" : "Coleta automática (fonte oficial)")}
    ${_campoDetalhe("Trecho da fonte", l.trecho_fonte)}
    <div class="meta" style="margin-top:10px;"><a href="${l.url_oficial}" target="_blank" rel="noopener">Ver na fonte oficial ↗</a></div>
  `;
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(
    "#ln-f-instituicao, #ln-f-setor, #ln-f-porte, #ln-f-regiao, #ln-f-status, #ln-f-fluxo, #linhas-ordenar"
  ).forEach((el) => el.addEventListener("change", () => loadLinhas(0)));
  document.getElementById("linhas-busca-btn").addEventListener("click", () => loadLinhas(0));
  document.getElementById("linhas-busca-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadLinhas(0);
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    if (btn.dataset.view === "linhas") {
      btn.addEventListener("click", async () => {
        await initLinhasFiltros();
        loadLinhas(0);
      }, { once: true });
    }
  });
});
