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
  let filtros;
  try {
    filtros = await fetchJSON("/api/linhas/filtros");
  } catch (e) {
    return; // selects ficam so com "Todas" -- a lista continua carregando
  }
  const fill = (id, values) => {
    const sel = document.getElementById(id);
    (values || []).forEach((v) => {
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
  return `<div class="result-card" data-id="${esc(l.id)}">
    <div class="top-row">
      <span class="cliente">${esc(l.nome_simplificado || l.nome_oficial)}</span>
      <span class="badge neutro">${esc(l.instituicao)}</span>
    </div>
    <div class="meta">${esc(l.setor_padronizado || "Setor não classificado")}${l.porte_padronizado ? " · " + esc(l.porte_padronizado) : ""}${l.regiao_elegivel ? " · " + esc(l.regiao_elegivel) : ""} · ${esc(l.status || "Não informado pela fonte")}</div>
    <div class="meta">${l.descricao_resumida ? esc(String(l.descricao_resumida).slice(0, 180)) : ""}</div>
    <div class="meta">${valor ? esc(valor) + " · " : ""}${l.taxa_completa && l.taxa_completa !== "Não informado pela fonte" ? esc(l.taxa_completa) : ""}</div>
    <div class="score">Atualizado em ${esc(atualizado)}${l.url_oficial ? ` · <a href="${escUrl(l.url_oficial)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">fonte oficial ↗</a>` : ""}</div>
  </div>`;
}

let _linhasToken = 0;
async function loadLinhas(pagina) {
  linhasPaginaAtual = pagina || 0;
  const container = document.getElementById("linhas-lista");
  container.innerHTML = '<p class="empty-state">Carregando linhas incentivadas...</p>';

  const filters = currentLinhasFilters();
  const [order_by, order_dir] = document.getElementById("linhas-ordenar").value.split("-");
  const offset = linhasPaginaAtual * LINHAS_PAGE_SIZE;

  const token = ++_linhasToken;
  let data;
  try {
    data = await fetchJSON("/api/linhas?" + qs({ ...filters, order_by, order_dir, limit: LINHAS_PAGE_SIZE, offset }));
  } catch (e) {
    if (token !== _linhasToken) return;
    container.innerHTML = '<p class="empty-state">Erro ao carregar linhas incentivadas. Tente novamente.</p>';
    document.getElementById("linhas-contagem").textContent = "";
    document.getElementById("linhas-paginacao").innerHTML = "";
    return;
  }
  if (token !== _linhasToken) return; // resposta de um filtro/pagina antigo
  data = data || {};
  data.resultados = Array.isArray(data.resultados) ? data.resultados : [];

  document.getElementById("linhas-contagem").textContent = `${fmtNum(data.total || 0)} linha(s) incentivada(s) encontrada(s)`;

  if (!data.resultados.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma linha incentivada encontrada para esses filtros.</p>';
    document.getElementById("linhas-paginacao").innerHTML = "";
    return;
  }

  container.innerHTML = data.resultados.map(linhaCard).join("");
  container.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", () => openLinhaDetalhe(card.dataset.id));
  });

  const totalPaginas = Math.max(1, Math.ceil((data.total || 0) / LINHAS_PAGE_SIZE));
  const pagContainer = document.getElementById("linhas-paginacao");
  if (totalPaginas <= 1) {
    pagContainer.innerHTML = "";
  } else {
    pagContainer.innerHTML = `
      <button class="pag-btn" id="linhas-pag-anterior" ${linhasPaginaAtual === 0 ? "disabled" : ""}>‹ Anterior</button>
      <span class="progress-label pag-info">Página ${linhasPaginaAtual + 1} de ${totalPaginas}</span>
      <button class="pag-btn" id="linhas-pag-proxima" ${linhasPaginaAtual + 1 >= totalPaginas ? "disabled" : ""}>Próxima ›</button>
    `;
    const btnAnt = document.getElementById("linhas-pag-anterior");
    const btnProx = document.getElementById("linhas-pag-proxima");
    if (btnAnt) btnAnt.addEventListener("click", () => loadLinhas(linhasPaginaAtual - 1));
    if (btnProx) btnProx.addEventListener("click", () => loadLinhas(linhasPaginaAtual + 1));
  }
}

// ============ Helpers de texto das linhas (compartilhados com potenciais.js) ============
// Regra (pedido do usuario 2026-09-25): nunca reescrever o texto da fonte -- no
// modal o resumo e SO corte em fronteira de palavra + "ver mais" com o integral;
// nos cards de Potenciais Linhas o resumo so extrai numeros literais do texto
// ("até N anos/meses", "N%") e marca "(varia)" quando a fonte lista casos.
const LN_NAO_INFORMADO = "Não informado pela fonte";
function lnNaoInformado(v) {
  return v === null || v === undefined || String(v).trim() === "" || v === LN_NAO_INFORMADO || v === "Não informado";
}

function lnCortarNaPalavra(texto, n) {
  const t = String(texto).trim();
  if (t.length <= n) return t;
  let c = t.slice(0, n);
  const i = c.lastIndexOf(" ");
  if (i > n * 0.6) c = c.slice(0, i);
  return c.replace(/[\s,;:.(\-–]+$/, "") + "…";
}

// Texto com "ver mais" inline -- o integral fica em data-full (escapado) e e
// trocado no clique (delegacao em lnLigarVerMais). Nunca corta no meio de palavra.
function lnTextoExpansivel(texto, n) {
  const t = String(texto).trim();
  if (t.length <= n + 20) return esc(t);
  const curto = lnCortarNaPalavra(t, n);
  return `<span class="ln-txt" data-full="${esc(t)}" data-curto="${esc(curto)}">${esc(curto)}</span> <button type="button" class="ln-mais-btn" aria-expanded="false">ver mais</button>`;
}

function lnLigarVerMais(container) {
  if (container.dataset.verMaisLigado) return;
  container.dataset.verMaisLigado = "1";
  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".ln-mais-btn");
    if (!btn) return;
    const span = btn.previousElementSibling;
    if (!span || !span.classList.contains("ln-txt")) return;
    const abrir = btn.getAttribute("aria-expanded") !== "true";
    span.textContent = abrir ? span.dataset.full : span.dataset.curto;
    btn.textContent = abrir ? "ver menos" : "ver mais";
    btn.setAttribute("aria-expanded", abrir ? "true" : "false");
  });
}

// "até N anos" a partir do texto da fonte (so numeros literais). null = sem
// numero reconhecivel (chamador cai pro corte simples).
function lnResumoDuracao(texto) {
  if (lnNaoInformado(texto)) return null;
  const t = String(texto).trim();
  if (t.length <= 26) return t.replace(/^Até/, "até").replace(/\.$/, "");
  const achados = [...t.matchAll(/(\d+(?:[.,]\d+)?)\s*(anos?|mes(?:es)?)\b/gi)].map((m) => {
    const n = parseFloat(m[1].replace(",", "."));
    return /^m/i.test(m[2]) ? n : n * 12;
  });
  if (!achados.length) return null;
  const maxMeses = Math.max(...achados);
  const rot = maxMeses >= 24 && maxMeses % 12 === 0 ? `${maxMeses / 12} anos` : `${maxMeses} meses`;
  return `até ${rot}${t.includes(";") ? " (varia)" : "…"}`;
}

function lnResumoPercentual(texto) {
  if (lnNaoInformado(texto)) return null;
  const t = String(texto);
  const achados = [...t.matchAll(/(\d{1,3}(?:[.,]\d+)?)\s*%/g)]
    .map((m) => parseFloat(m[1].replace(",", "."))).filter((v) => v <= 100);
  if (!achados.length) return null;
  const max = Math.max(...achados);
  return `até ${String(max).replace(".", ",")}%${t.includes(";") ? " (varia)" : ""}`;
}

function lnResumoTaxa(texto, indexador) {
  if (lnNaoInformado(texto)) return lnNaoInformado(indexador) ? null : String(indexador);
  const t = String(texto).trim().replace(/^Taxa\s+(de\s+juros\s+)?/i, (m) => (/juros/i.test(m) ? "Juros " : ""));
  const cmn = t.match(/CMN\)?\s*n?º?\s*(\d[\d.]*\d)/i);
  if (cmn) {
    const ano = (t.match(/\/(\d{4})/) || [])[1];
    return `Conforme Res. CMN nº ${cmn[1]}${ano ? "/" + ano : ""}`;
  }
  if (t.length <= 44) return t.replace(/\.$/, "");
  const idx = [...new Set((t.match(/\b(TLP|TJLP|Selic|IPCA|TR|CDI|TFC|prefixad[ao])\b/gi) || [])
    .map((x) => (/^prefix/i.test(x) ? "prefixada" : x.toUpperCase() === "SELIC" ? "Selic" : x.toUpperCase())))];
  if (idx.length) return `${idx.join(" ou ")} + encargos (varia)`;
  return lnCortarNaPalavra(t, 44);
}

// ============ Modal de detalhe da linha (redesenho 2026-09-25) ============
// Cabecalho limpo, 4 destaques em tipografia normal, resto em lista de definicao
// 2 colunas, "Não informado" agrupado no rodape, textos longos com "ver mais".
function _lnDlItem(rotulo, valor, naoInformados, limite) {
  if (lnNaoInformado(valor)) { naoInformados.push(rotulo); return ""; }
  return `<dt>${esc(rotulo)}</dt><dd>${lnTextoExpansivel(valor, limite || 220)}</dd>`;
}

function _lnSecao(titulo, itensHtml) {
  const conteudo = itensHtml.filter(Boolean).join("");
  if (!conteudo) return "";
  return `<h3 class="ln-secao">${esc(titulo)}</h3><dl class="ln-dl">${conteudo}</dl>`;
}

async function openLinhaDetalhe(id) {
  document.getElementById("modal-title").textContent = "Linha incentivada";
  document.getElementById("modal-ordenar").style.display = "none";
  document.getElementById("modal-copiar-link-btn").style.display = "none";
  document.getElementById("modal-favoritar-btn").classList.add("hidden");
  document.getElementById("modal-nota-container").classList.add("hidden");
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");
  const fechar = document.getElementById("modal-close");
  if (fechar) fechar.focus();

  let l;
  try {
    l = await fetchJSON(`/api/linhas/${encodeURIComponent(id)}`);
  } catch (e) {
    body.innerHTML = htmlErroCarga("Não foi possível carregar esta linha agora. Tente novamente em instantes.");
    return;
  }
  if (!l || l.erro) {
    body.innerHTML = `<p class="empty-state">${esc((l && l.erro) || "Linha não encontrada.")}</p>`;
    return;
  }
  document.getElementById("modal-title").textContent = l.nome_oficial || "Linha incentivada";

  const naoInf = [];
  const destaque = (rotulo, valor) => {
    if (lnNaoInformado(valor)) { naoInf.push(rotulo); return ""; }
    return `<div class="ln-destaque"><div class="rot">${esc(rotulo)}</div><div class="val">${lnTextoExpansivel(valor, 110)}</div></div>`;
  };
  const taxaTxt = [l.taxa_completa, [l.indexador, l.spread].filter((v) => !lnNaoInformado(v)).join(" · ")]
    .filter((v) => !lnNaoInformado(v)).join(" — ");
  const destaques = [
    destaque("Taxa", taxaTxt),
    destaque("Prazo", l.prazo_total),
    destaque("Carência", l.carencia),
    destaque("Participação", l.percentual_financiavel),
  ].join("");

  const descricao = !lnNaoInformado(l.descricao_completa) ? l.descricao_completa : l.descricao_resumida;
  const cab = [
    `<span class="badge neutro">${esc(l.instituicao)}</span>`,
    l.status ? `<span>${esc(l.status.charAt(0).toUpperCase() + l.status.slice(1))}</span>` : "",
    `<span>${l.fluxo === "edital" ? "Edital / chamada pública" : "Fluxo contínuo"}</span>`,
    !lnNaoInformado(l.agente_financeiro) ? `<span>Agente: ${esc(lnCortarNaPalavra(l.agente_financeiro, 60))}</span>` : "",
  ].filter(Boolean).join('<span aria-hidden="true">·</span>');

  const secoes = [
    _lnSecao("Quem pode acessar", [
      _lnDlItem("Porte elegível", l.porte_padronizado, naoInf),
      _lnDlItem("Setores elegíveis", l.setores_elegiveis, naoInf),
      _lnDlItem("Setores não elegíveis", l.setores_nao_elegiveis, naoInf),
      _lnDlItem("Região", l.regiao_elegivel, naoInf),
      _lnDlItem("Faixa de receita", l.faixa_receita, naoInf),
      _lnDlItem("Enquadramento", l.criterios_elegibilidade, naoInf),
    ]),
    _lnSecao("O que financia", [
      _lnDlItem("Valor / limites", fmtValorLinha(l.valor_minimo, l.valor_maximo), naoInf),
      _lnDlItem("Destinação", l.destinacao, naoInf),
      _lnDlItem("Itens financiáveis", l.itens_financiaveis, naoInf),
      _lnDlItem("Itens não financiáveis", l.itens_nao_financiaveis, naoInf),
      _lnDlItem("Contrapartida", l.contrapartida, naoInf),
    ]),
    _lnSecao("Condições e contratação", [
      _lnDlItem("Amortização", l.amortizacao, naoInf),
      _lnDlItem("Garantias", l.garantias, naoInf),
      _lnDlItem("Restrições", l.restricoes, naoInf),
      _lnDlItem("Modalidade", l.modalidade, naoInf),
      _lnDlItem("Tipo de apoio", l.tipo_apoio, naoInf),
      _lnDlItem("Canal de contratação", l.canal_contratacao, naoInf),
      _lnDlItem("Prazo de inscrição", l.prazo_inscricao, naoInf),
      _lnDlItem("Documentos", l.documentos_necessarios, naoInf),
      _lnDlItem("Vigência", l.data_vigencia, naoInf),
    ]),
  ].join("");

  const dataBR = (d) => (d ? new Date(d).toLocaleDateString("pt-BR") : null);
  const fonte = [
    l.url_oficial ? `<a href="${escUrl(l.url_oficial)}" target="_blank" rel="noopener noreferrer">Fonte oficial ↗</a>` : "",
    l.data_atualizacao ? `Atualizado em ${esc(dataBR(l.data_atualizacao))}` : "",
    l.origem_dado === "curadoria_manual_verificada" ? "Curadoria manual verificada" : "Coleta automática da fonte oficial",
  ].filter(Boolean).join(" · ");

  body.innerHTML = `
    <div class="ln-cab">${cab}</div>
    ${!lnNaoInformado(descricao) ? `<p class="ln-desc">${lnTextoExpansivel(descricao, 320)}</p>` : ""}
    ${destaques ? `<div class="ln-destaques">${destaques}</div>` : ""}
    ${secoes}
    <div id="ln-relacionadas-slot"></div>
    <div class="ln-rodape">
      ${naoInf.length ? `<div>Não informado pela fonte: ${esc(naoInf.join(", "))}</div>` : ""}
      <div>${fonte}</div>
      ${!lnNaoInformado(l.trecho_fonte) ? `<details><summary>Trecho da fonte</summary><div class="ln-trecho">${esc(l.trecho_fonte)}</div></details>` : ""}
    </div>
  `;
  lnLigarVerMais(body);

  // Integracao transacoes <-> linhas: so quando o setor da linha usa a mesma
  // taxonomia de operations.setor_bndes (4 categorias BNDES) -- nunca e
  // confirmacao de elegibilidade, so atalho pra referencias historicas.
  const SETORES_TAXONOMIA_BNDES = ["AGROPECUÁRIA", "COMERCIO/SERVICOS", "INDUSTRIA", "INFRAESTRUTURA"];
  if (l.setor_padronizado && SETORES_TAXONOMIA_BNDES.includes(l.setor_padronizado)) {
    const slot = document.getElementById("ln-relacionadas-slot");
    if (slot) {
      slot.innerHTML = `<div class="ln-relacionadas">
        <span>Operações do setor <strong>${esc(l.setor_padronizado)}</strong> na base (referência, não confirma elegibilidade).</span>
        <button type="button" class="pt-btn" id="ln-ver-operacoes-relacionadas">Ver operações do setor</button>
      </div>`;
      document.getElementById("ln-ver-operacoes-relacionadas").addEventListener("click", () => {
        openOperacoesModal(`Setor: ${l.setor_padronizado} (potencialmente compatível com "${l.nome_simplificado || l.nome_oficial}")`, { setor: l.setor_padronizado });
      });
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
    debounce(() => {
      _sincronizarFiltrosLinhasNaURL();
      loadLinhas(0);
    }, 300)
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
