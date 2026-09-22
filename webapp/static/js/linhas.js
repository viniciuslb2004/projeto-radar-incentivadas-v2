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
    // "porte" aqui e o bucket canonico (porte_grupo, ver docs/linhas-incentivadas.md
    // e webapp/main.py::_linhas_where) -- o <select> so lista os ~5 valores do
    // bucket, nunca os 42 valores brutos de porte_padronizado.
    porte: document.getElementById("ln-f-porte").value,
    regiao: document.getElementById("ln-f-regiao").value,
    fluxo: document.getElementById("ln-f-fluxo").value,
    q: document.getElementById("linhas-busca-input").value.trim(),
  };
}

// ============ Filtros na URL (ver secao "Filtros na URL" em common.js) ============
// linhas-ordenar (ordenacao) e a pagina atual da paginacao ficam DE FORA de
// proposito -- mesma logica ja aplicada a granularidade do grafico de serie
// temporal em common.js e a ordenacao de Editais: mudam so como/em que ordem os
// mesmos dados sao exibidos, nao qual fatia deles aparece.
function _sincronizarFiltrosLinhasNaURL() {
  sincronizarFiltrosNaURL(currentLinhasFilters());
}

function _aplicarFiltrosLinhasDaURL() {
  const params = paramsDaURL();
  const CAMPO_PARA_ID = {
    instituicao: "ln-f-instituicao",
    setor: "ln-f-setor",
    porte: "ln-f-porte",
    regiao: "ln-f-regiao",
    fluxo: "ln-f-fluxo",
  };
  Object.entries(CAMPO_PARA_ID).forEach(([campo, id]) => {
    if (params.has(campo)) document.getElementById(id).value = params.get(campo);
  });
  if (params.has("q")) document.getElementById("linhas-busca-input").value = params.get("q");
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

// Card mini de "resumo executivo" -- mesma classe .kpi-card ja usada no
// Consolidado (grid de estatisticas), reaproveitada aqui em vez de criar CSS
// novo. "-" quando o campo nao foi informado pela fonte (nunca esconde o card,
// sempre mostra que o dado nao existe -- diferente de omitir a linha inteira).
function _kpiMiniDetalhe(rotulo, valor, sub) {
  const texto = (valor === null || valor === undefined || valor === "" || valor === "Não informado pela fonte")
    ? "Não informado" : valor;
  return `<div class="kpi-card">
    <div class="label">${rotulo}</div>
    <div class="value" style="font-size:16px;">${texto}</div>
    ${sub ? `<div class="sub">${sub}</div>` : ""}
  </div>`;
}

// Texto completo expansivel (gap-fix 2026-09-22, item 2): Enquadramento
// (criterios_elegibilidade) e "O que pode ser financiado" (itens_financiaveis)
// so apareciam truncados em 80 caracteres no resumo executivo (ver
// _kpiMiniDetalhe abaixo) -- sem NENHUM lugar com o texto integral. Acordeao
// nativo <details>/<summary> (sem lib nova) nas secoes secundarias, junto de
// descricao_completa/garantias/restricoes (que ja mostram texto integral) --
// mesma classe .meta do resto do detalhe, so fica fechado por padrao.
function _campoDetalheExpansivel(rotulo, valor) {
  if (valor === null || valor === undefined || valor === "") return "";
  return `<div class="meta" style="margin-top:6px;">
    <details>
      <summary style="cursor:pointer;"><strong>${rotulo}</strong> <span class="hint">(ver texto completo)</span></summary>
      <div style="margin-top:6px;">${valor}</div>
    </details>
  </div>`;
}

// Secao com titulo (reaproveita .card/.card-header, ja usados no resto do site)
// -- so renderiza se tiver ao menos 1 campo preenchido, pra nao mostrar um card
// vazio so com titulo.
function _secaoDetalhe(titulo, camposHtml) {
  const conteudo = camposHtml.filter(Boolean).join("");
  if (!conteudo) return "";
  return `<div class="card" style="margin-top:14px;">
    <div class="card-header">${titulo}</div>
    <div class="card-body">${conteudo}</div>
  </div>`;
}

async function openLinhaDetalhe(id) {
  document.getElementById("modal-title").textContent = "Linha incentivada";
  const ordenarSelect = document.getElementById("modal-ordenar");
  ordenarSelect.style.display = "none";
  document.getElementById("modal-copiar-link-btn").style.display = "none";
  document.getElementById("modal-favoritar-btn").classList.add("hidden");
  document.getElementById("modal-nota-container").classList.add("hidden");
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const l = await fetchJSON(`/api/linhas/${id}`);
  if (l.erro) {
    body.innerHTML = `<p class="empty-state">${l.erro}</p>`;
    return;
  }
  document.getElementById("modal-title").textContent = l.nome_oficial;

  // Reorganizacao (item 2 do pedido, revisada no gap-fix de 2026-09-22 item 1):
  // "resumo executivo" no topo, pensado pra responder rapido "essa linha serve
  // pro meu projeto?" -- ordem final: Taxa/Prazo/Carência/Participação no
  // projeto/Volume-limites/Enquadramento/O que pode ser financiado/Porte
  // elegível/Setores aplicáveis. Volume-limites, Porte elegível e Setores
  // aplicáveis SUBIRAM pro destaque (antes so apareciam mais abaixo, em secoes
  // secundarias) -- removidos de la pra nao duplicar (ver secoes "Setores e
  // público-alvo"/"Condições adicionais" mais abaixo). Nenhum campo foi
  // escondido, so reordenado/promovido.
  const resumo = `
    <div class="kpi-row" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));margin-top:10px;">
      ${_kpiMiniDetalhe("Taxa", l.taxa_completa, [l.indexador, l.spread].filter((v) => v && v !== "Não informado pela fonte").join(" · ") || null)}
      ${_kpiMiniDetalhe("Prazo", l.prazo_total)}
      ${_kpiMiniDetalhe("Carência", l.carencia)}
      ${_kpiMiniDetalhe("Participação no projeto", l.percentual_financiavel)}
      ${_kpiMiniDetalhe("Volume/limites", fmtValorLinha(l.valor_minimo, l.valor_maximo))}
      ${_kpiMiniDetalhe("Enquadramento", l.criterios_elegibilidade ? l.criterios_elegibilidade.slice(0, 80) + (l.criterios_elegibilidade.length > 80 ? "…" : "") : null)}
      ${_kpiMiniDetalhe("O que pode ser financiado", l.itens_financiaveis ? l.itens_financiaveis.slice(0, 80) + (l.itens_financiaveis.length > 80 ? "…" : "") : null)}
      ${_kpiMiniDetalhe("Porte elegível", l.porte_padronizado)}
      ${_kpiMiniDetalhe("Setores aplicáveis", l.setores_elegiveis)}
    </div>
  `;

  body.innerHTML = `
    <div class="meta"><span class="badge neutro">${l.instituicao}</span> · ${l.status || "Não informado pela fonte"} · ${l.fluxo === "edital" ? "Edital/chamada pública" : "Fluxo contínuo"}</div>
    ${resumo}
    ${_secaoDetalhe("Descrição", [
      _campoDetalhe("Descrição completa", l.descricao_completa),
      _campoDetalheExpansivel("Enquadramento (critérios de elegibilidade) -- texto completo", l.criterios_elegibilidade),
      _campoDetalheExpansivel("O que pode ser financiado -- texto completo", l.itens_financiaveis),
    ])}
    ${_secaoDetalhe("Instituição", [
      _campoDetalhe("Agente financeiro", l.agente_financeiro),
      _campoDetalhe("Canal de contratação", l.canal_contratacao),
      _campoDetalhe("Modalidade", l.modalidade),
      _campoDetalhe("Tipo de apoio", l.tipo_apoio),
    ])}
    ${_secaoDetalhe("Setores e público-alvo", [
      _campoDetalhe("Setores não elegíveis", l.setores_nao_elegiveis),
      _campoDetalhe("Faixa de receita", l.faixa_receita),
      _campoDetalhe("Região elegível", l.regiao_elegivel),
      _campoDetalhe("Destinação", l.destinacao),
    ])}
    ${_secaoDetalhe("Condições adicionais", [
      _campoDetalhe("Itens não financiáveis", l.itens_nao_financiaveis),
      _campoDetalhe("Contrapartida", l.contrapartida),
      _campoDetalhe("Amortização", l.amortizacao),
      _campoDetalhe("Prazo de inscrição", l.prazo_inscricao),
      _campoDetalhe("Documentos necessários", l.documentos_necessarios),
    ])}
    ${_secaoDetalhe("Garantias", [_campoDetalhe("Garantias", l.garantias)])}
    ${_secaoDetalhe("Observações", [_campoDetalhe("Restrições", l.restricoes)])}
    ${_secaoDetalhe("Fonte", [
      _campoDetalhe("Data de vigência", l.data_vigencia),
      _campoDetalhe("Capturado em", l.data_captura ? new Date(l.data_captura).toLocaleDateString("pt-BR") : null),
      _campoDetalhe("Atualizado em", l.data_atualizacao ? new Date(l.data_atualizacao).toLocaleDateString("pt-BR") : null),
      _campoDetalhe("Origem do dado", l.origem_dado === "curadoria_manual_verificada" ? "Curadoria manual verificada" : "Coleta automática (fonte oficial)"),
      _campoDetalhe("Trecho da fonte", l.trecho_fonte),
    ])}
    <div class="meta" style="margin-top:10px;"><a href="${l.url_oficial}" target="_blank" rel="noopener">Ver na fonte oficial ↗</a></div>
  `;

  // Integracao transacoes <-> linhas incentivadas (item 8): so mostra quando o setor
  // desta linha usa a MESMA taxonomia de `operations.setor_bndes` (as 4 categorias
  // nativas do BNDES) -- setor_padronizado de linhas vindas de editais da FINEP usa
  // o tema_principal da FINEP (outra taxonomia, incompativel), e cruzar as duas sem
  // um de-para real produziria "0 encontrado" enganoso em vez de simplesmente nao
  // mostrar a secao. Nunca confunde os dois tipos de resultado -- e so uma contagem
  // + link pro modal generico de operacoes, rotulado como "potencialmente compativel"
  // (nao elegibilidade confirmada -- ver item 8 do pedido).
  const SETORES_TAXONOMIA_BNDES = ["AGROPECUÁRIA", "COMERCIO/SERVICOS", "INDUSTRIA", "INFRAESTRUTURA"];
  if (l.setor_padronizado && SETORES_TAXONOMIA_BNDES.includes(l.setor_padronizado)) {
    try {
      const relacionadas = await fetchJSON("/api/operacoes?" + qs({ setor: l.setor_padronizado, limit: 1 }) + "&offset=0");
      const contagemDiv = document.createElement("div");
      contagemDiv.className = "card";
      contagemDiv.style.marginTop = "14px";
      contagemDiv.innerHTML = `
        <div class="card-header">Transações potencialmente relacionadas <span class="hint">mesmo setor -- não é confirmação de elegibilidade</span></div>
        <div class="card-body">
          <p class="meta">Já existem operações de crédito classificadas no setor <strong>${l.setor_padronizado}</strong> na base deste app.</p>
          <button class="acao-btn" id="ln-ver-operacoes-relacionadas">Ver operações deste setor</button>
        </div>
      `;
      body.appendChild(contagemDiv);
      document.getElementById("ln-ver-operacoes-relacionadas").addEventListener("click", () => {
        openOperacoesModal(`Setor: ${l.setor_padronizado} (potencialmente compatível com "${l.nome_simplificado || l.nome_oficial}")`, { setor: l.setor_padronizado });
      });
    } catch (e) {
      // integracao e um extra -- se a chamada falhar, so nao mostra a secao, sem quebrar o resto do detalhe.
    }
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(
    "#ln-f-instituicao, #ln-f-setor, #ln-f-porte, #ln-f-regiao, #ln-f-fluxo"
  ).forEach((el) => el.addEventListener("change", () => {
    _sincronizarFiltrosLinhasNaURL();
    loadLinhas(0);
  }));
  document.getElementById("linhas-ordenar").addEventListener("change", () => loadLinhas(0));
  document.getElementById("linhas-busca-btn").addEventListener("click", () => {
    _sincronizarFiltrosLinhasNaURL();
    loadLinhas(0);
  });
  document.getElementById("linhas-busca-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      _sincronizarFiltrosLinhasNaURL();
      loadLinhas(0);
    }
  });
  // Digitar sem apertar Enter/clicar tambem deve refletir na URL depois que o
  // usuario para de digitar (debounce), sem forcar uma nova busca a cada tecla.
  document.getElementById("linhas-busca-input").addEventListener(
    "input",
    debounce(_sincronizarFiltrosLinhasNaURL, 400)
  );

  // Antes so carregava filtros/lista no CLICK da aba "Linhas Incentivadas" -- com as
  // rotas por caminho (/linhas-incentivadas), entrar direto pela URL ou dar F5 nunca
  // clica o botao da aba, entao a pagina ficava vazia pra sempre. Carrega igual as
  // outras abas (ver editais.js/tendencias.js): incondicional, ja no DOMContentLoaded.
  await initLinhasFiltros();

  // Link compartilhado/F5: aplica os filtros da URL so depois das opcoes acima
  // estarem populadas, e so quando a aba ativa na URL e de fato Linhas
  // Incentivadas (ver _viewInicialDaURL).
  if (_viewInicialDaURL() === "linhas") _aplicarFiltrosLinhasDaURL();

  loadLinhas(0);
});
