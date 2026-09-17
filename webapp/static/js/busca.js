// Aba Busca: texto livre -> operacoes parecidas. Por padrao usa o motor sem IA
// (full-text/trigram, ver src/search_fts.py); so usa embeddings se o servidor tiver
// MOTOR_BUSCA_IA=1 ligado (ver window.BUSCA_IA_ATIVA, definido em common.js).

let ultimosResultados = [];

// Ids de operacao ja salvos do usuario logado (Transacoes Salvas) -- carregado 1x
// por busca (ver runBusca) via /api/salvos/operacoes/ids (rota em lote, ver
// webapp/main.py::salvos_ids), NUNCA um GET por card: os resultados podem trazer
// ate 200 linhas, e cada card ja tem sua propria estrelinha (`.fav-btn-mini`, ver
// renderListaResultados) que precisa saber, de cara, se aquela operacao ja esta
// favoritada. Vazio (nunca erro) tanto pra "ninguem logado" quanto pra qualquer
// falha de rede -- nesses casos nenhuma estrela nasce preenchida, mas a busca em
// si segue funcionando normalmente.
let idsSalvosAtual = new Set();

async function _carregarIdsSalvos() {
  try {
    const data = await fetchJSON("/api/salvos/operacoes/ids");
    idsSalvosAtual = new Set(data.ids || []);
  } catch (e) {
    idsSalvosAtual = new Set();
  }
}

// Historico de buscas: pessoal e temporario (so no navegador da propria pessoa,
// via localStorage -- nunca vai pro servidor). Substitui os chips de exemplo
// fixos que existiam antes (pedido do usuario).
// Chave escopada por usuario logado (obterUsuarioAtual(), ver common.js): sem
// isso, duas contas diferentes logando no MESMO navegador enxergavam o mesmo
// historico (localStorage e por origem, nao por sessao/conta) -- bug real
// reportado pelo usuario em 2026-09-11. Sem login individual configurado
// (usuario null), cai na chave antiga sem sufixo, preservando o comportamento
// de antes da conta.
const BUSCA_HISTORICO_KEY_BASE = "radar_busca_historico";
const BUSCA_HISTORICO_MAX = 8;

async function _chaveHistoricoBusca() {
  const usuario = await obterUsuarioAtual();
  return usuario ? `${BUSCA_HISTORICO_KEY_BASE}:${usuario}` : BUSCA_HISTORICO_KEY_BASE;
}

async function carregarHistoricoBusca() {
  try {
    const chave = await _chaveHistoricoBusca();
    const bruto = localStorage.getItem(chave);
    const lista = bruto ? JSON.parse(bruto) : [];
    return Array.isArray(lista) ? lista : [];
  } catch (e) {
    return [];
  }
}

async function registrarHistoricoBusca(q) {
  try {
    const chave = await _chaveHistoricoBusca();
    const atual = (await carregarHistoricoBusca()).filter((item) => item.toLowerCase() !== q.toLowerCase());
    atual.unshift(q);
    localStorage.setItem(chave, JSON.stringify(atual.slice(0, BUSCA_HISTORICO_MAX)));
  } catch (e) {
    // localStorage indisponivel (aba privada, storage bloqueado) -- historico so nao aparece.
  }
  await renderHistoricoBusca();
}

async function renderHistoricoBusca() {
  const container = document.getElementById("busca-historico");
  const input = document.getElementById("busca-input");
  const historico = await carregarHistoricoBusca();

  if (!historico.length) {
    container.style.display = "none";
    container.innerHTML = "";
    return;
  }

  container.style.display = "flex";
  container.innerHTML =
    historico.map((q) => `<span class="chip" data-q="${q.replace(/"/g, "&quot;")}">${q}</span>`).join("") +
    '<span class="chip chip-limpar" id="busca-historico-limpar">Limpar histórico</span>';

  container.querySelectorAll(".chip[data-q]").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.q;
      runBusca(chip.dataset.q);
    });
  });
  const limpar = document.getElementById("busca-historico-limpar");
  if (limpar) {
    limpar.addEventListener("click", async () => {
      try {
        localStorage.removeItem(await _chaveHistoricoBusca());
      } catch (e) {
        // ignora
      }
      renderHistoricoBusca();
    });
  }
}

function ordenarResultados(lista, criterio) {
  const copia = [...lista];
  switch (criterio) {
    case "data-desc":
      return copia.sort((a, b) => (b.data_contratacao || "").localeCompare(a.data_contratacao || ""));
    case "data-asc":
      return copia.sort((a, b) => (a.data_contratacao || "").localeCompare(b.data_contratacao || ""));
    case "valor-desc":
      return copia.sort((a, b) => (b.valor_contratado || 0) - (a.valor_contratado || 0));
    case "valor-asc":
      return copia.sort((a, b) => (a.valor_contratado || 0) - (b.valor_contratado || 0));
    case "agencia-asc":
      return copia.sort((a, b) => (a.agencia || "").localeCompare(b.agencia || ""));
    default:
      return copia.sort((a, b) => (b.score || 0) - (a.score || 0));
  }
}

function renderListaResultados() {
  const criterio = document.getElementById("busca-ordenar").value;
  const lista = ordenarResultados(ultimosResultados, criterio);
  const container = document.getElementById("busca-lista");

  if (!lista.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma operação parecida encontrada.</p>';
    return;
  }

  // Suposicao de contrato (ver CLAUDE.md): GET /api/primario/busca devolve
  // resultados com nomes de campo proprios do dominio CVM (emissor/
  // instrumento/setor_emissor/data_referencia/valor_emissao) -- fallback pro
  // nome "generico" (mesmo usado pelo Incentivado) cobre o caso do backend
  // real acabar espelhando os MESMOS nomes por conveniencia.
  container.innerHTML = lista
    .map((r) => {
      const nomeCliente = r.cliente ?? r.emissor ?? r.razao_social_oficial_emissor;
      const nomeAgencia = r.agencia ?? r.instrumento ?? r.instrumento_padronizado;
      const nomeSetor = r.setor_bndes ?? r.setor_emissor;
      const nomeSubsetor = r.subsetor_bndes ?? r.subsetor_emissor;
      const nomeSegmento = r.segmento ?? r.segmento_emissor;
      const nomeData = r.data_contratacao ?? r.data_referencia;
      const nomeValor = r.valor_contratado ?? r.valor_emissao ?? r.valor_oferta;
      // Estrelinha de favoritar: escondida no Primario -- "Transacoes Salvas"
      // ainda nao suporta operations_primario (ver TODO em
      // common.js::_configurarBotaoFavoritar).
      const favBtn = _mercadoAtivo === "primario"
        ? ""
        : `<button class="fav-btn-mini${idsSalvosAtual.has(r.id) ? " ativo" : ""}" data-op-id="${r.id}" title="${idsSalvosAtual.has(r.id) ? "Remover dos salvos" : "Salvar operação"}">${idsSalvosAtual.has(r.id) ? "★" : "☆"}</button>`;
      return `<div class="result-card" data-id="${r.id}">
        ${favBtn}
        <div class="top-row">
          <span class="cliente">${nomeCliente || "-"}</span>
          <span class="valor">${fmtBRLFull(nomeValor)}</span>
        </div>
        <div class="meta">${nomeAgencia || "-"} · ${nomeSetor || "Não classificado"}${nomeSubsetor ? " · " + nomeSubsetor : ""}${nomeSegmento ? " · " + nomeSegmento : ""} · ${r.uf || "-"} · ${nomeData || "-"}</div>
        <div class="meta">${r.descricao_projeto ? r.descricao_projeto.slice(0, 160) : ""}</div>
        <div class="score">${typeof r.score === "number" ? `similaridade: ${(r.score * 100).toFixed(0)}%` : r.motivo || ""}</div>
      </div>`;
    })
    .join("");

  container.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", () => openOperacaoDetalhe(card.dataset.id));
  });

  // Estrelinha mini (só aparece no hover do card, ver .fav-btn-mini em style.css) --
  // favorita/desfavorita sem abrir o modal de detalhe. stopPropagation() é
  // essencial aqui: o card inteiro (acima) já tem seu próprio click que abre o
  // modal, e os dois nunca devem disparar juntos. UI otimista (ver
  // common.js::alternarFavoritoOtimista) -- pinta ★/☆ na hora do clique, só
  // reverte se a chamada ao servidor falhar.
  container.querySelectorAll(".fav-btn-mini").forEach((btn) => {
    const opId = Number(btn.dataset.opId);
    const renderizar = (ativo) => {
      btn.classList.toggle("ativo", ativo);
      btn.textContent = ativo ? "★" : "☆";
      btn.title = ativo ? "Remover dos salvos" : "Salvar operação";
      if (ativo) idsSalvosAtual.add(opId);
      else idsSalvosAtual.delete(opId);
    };
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      alternarFavoritoOtimista(btn, opId, btn.classList.contains("ativo"), renderizar, () => {
        if (typeof recarregarSalvos === "function") recarregarSalvos();
      });
    });
  });
}

function renderResultados(data) {
  ultimosResultados = data.resultados || [];
  let html = "";

  if (data.confianca_baixa) {
    const baseTxt = _mercadoAtivo === "primario" ? "na base de ofertas do mercado de capitais (CVM)" : "na base do BNDES/FINEP";
    html += `<div class="confianca-baixa-aviso">⚠ Não encontramos uma correspondência forte para "${data.query}" ${baseTxt}. Os resultados abaixo são os mais próximos disponíveis, mas com similaridade baixa (${Math.round(data.melhor_score * 100)}%).</div>`;
  }
  if (data.enriquecido_via_web) {
    html += `<div class="confianca-baixa-aviso">🔎 Resultados ajustados depois de pesquisar sobre "${data.query_original || data.query}" na web, para tentar entender melhor do que se trata.</div>`;
  }

  // Taxa de aprovacao (Crédito Direto FINEP) -- sem equivalente no mercado
  // de capitais (nao existe um rito de "aprovacao/recusa de projeto" pra uma
  // oferta publica de debenture/CRI/CRA); escondida de proposito no Primario.
  const prob = _mercadoAtivo === "primario" ? null : data.probabilidade_aprovacao;
  if (prob) {
    if (prob.disponivel) {
      html += `<div class="aprovacao-box aprovacao-disponivel">
        <div class="aprovacao-taxa">${prob.taxa_pct.toFixed(1).replace(".", ",")}%</div>
        <div>
          <div class="aprovacao-titulo">Taxa histórica de aprovação · Crédito Direto (FINEP)</div>
          <div class="aprovacao-detalhe">Baseado em ${fmtNum(prob.aprovados)} projetos aprovados e ${fmtNum(prob.recusados)} não aprovados no histórico público da FINEP.</div>
        </div>
      </div>`;
    } else if (prob.motivo) {
      html += `<div class="aprovacao-box aprovacao-indisponivel">
        <div class="aprovacao-titulo">Taxa de aprovação: não disponível</div>
        <div class="aprovacao-detalhe">${prob.motivo}</div>
      </div>`;
    }
  }

  html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:10px;">
    <span class="progress-label" id="busca-contagem">${fmtNum(ultimosResultados.length)} operações parecidas encontradas</span>
    <div style="display:flex; gap:8px; align-items:center;">
      <button id="busca-exportar-btn" class="acao-btn" style="padding:6px 12px; font-size:13px;">Exportar Excel</button>
      <select id="busca-ordenar" class="header-select" style="color:var(--navy); border-color:var(--border); background:#fff;">
        <option value="relevancia">Mais relevante</option>
        <option value="data-desc">Mais recente</option>
        <option value="data-asc">Mais antiga</option>
        <option value="valor-desc">Maior valor</option>
        <option value="valor-asc">Menor valor</option>
        <option value="agencia-asc">Agência (A-Z)</option>
      </select>
    </div>
  </div>`;
  html += '<div id="busca-lista"></div>';

  document.getElementById("busca-resultado").innerHTML = html;
  document.getElementById("busca-ordenar").addEventListener("change", renderListaResultados);
  document.getElementById("busca-exportar-btn").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    const textoOriginal = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Gerando...";
    try {
      // Reenvia as MESMAS linhas ja renderizadas na tela (ultimosResultados) -- o
      // backend monta o .xlsx em cima delas, nunca re-roda a busca, pra garantir que
      // o arquivo bate exatamente com o que a pessoa viu (ver webapp/exportar_excel.py).
      const resp = await fetch("/api/busca/exportar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: data.query, resultados: ultimosResultados }),
      });
      if (!resp.ok) throw new Error("falha ao gerar excel");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `busca-${(data.query || "resultado").replace(/[^a-z0-9]+/gi, "-")}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Não foi possível gerar o Excel. Tente novamente.");
    } finally {
      btn.disabled = false;
      btn.textContent = textoOriginal;
    }
  });
  renderListaResultados();
}

// #bu-f-agencia e #bu-f-produto sao os MESMOS 2 selects reaproveitados com
// significado diferente por mercado -- "Entidade"/"Tipo de linha" (BNDES/
// FINEP) no Incentivado, "Instrumento"/"Indexador" (CVM) no Primario. Ver
// _aplicarRotulosMercadoBusca() (troca os <label>) e _popularFiltrosBusca()
// (troca as <option>).
function _filtrosBusca() {
  // Valor minimo e digitado em R$ MILHOES na UI (ex: "15" = R$15.000.000) -- mais
  // facil de digitar do que o valor cheio; a API continua recebendo o valor real
  // (em reais), so a multiplicacao por 1e6 acontece aqui.
  const valorMinimoMilhoes = document.getElementById("bu-f-valor-minimo").value;
  const filtros = {
    valor_minimo: valorMinimoMilhoes ? Number(valorMinimoMilhoes) * 1e6 : "",
    regiao: document.getElementById("bu-f-regiao").value,
    porte: document.getElementById("bu-f-porte").value,
    setor: document.getElementById("bu-f-setor").value,
    uf: document.getElementById("bu-f-uf").value,
  };
  if (_mercadoAtivo === "primario") {
    filtros.instrumento = document.getElementById("bu-f-agencia").value;
    filtros.indexador = document.getElementById("bu-f-produto").value;
  } else {
    filtros.agencia = document.getElementById("bu-f-agencia").value;
    filtros.produto = document.getElementById("bu-f-produto").value;
  }
  return filtros;
}

// ============ Filtros na URL (ver secao "Filtros na URL" em common.js) ============
// valor_minimo entra na URL na MESMA UNIDADE exibida no campo (R$ milhoes) -- ao
// contrario de _filtrosBusca() (que ja multiplica por 1e6 pra mandar pra API),
// aqui guardamos o valor cru pra nao converter de novo na hora de ler de volta.
function _sincronizarFiltrosBuscaNaURL(q) {
  const params = {
    q: q || "",
    valor_minimo: document.getElementById("bu-f-valor-minimo").value,
    regiao: document.getElementById("bu-f-regiao").value,
    porte: document.getElementById("bu-f-porte").value,
    setor: document.getElementById("bu-f-setor").value,
    uf: document.getElementById("bu-f-uf").value,
  };
  if (_mercadoAtivo === "primario") {
    params.instrumento = document.getElementById("bu-f-agencia").value;
    params.indexador = document.getElementById("bu-f-produto").value;
  } else {
    params.agencia = document.getElementById("bu-f-agencia").value;
    params.produto = document.getElementById("bu-f-produto").value;
  }
  sincronizarFiltrosNaURL(params);
}

function _aplicarFiltrosBuscaDaURL() {
  const params = paramsDaURL();
  const chaveTopo = _mercadoAtivo === "primario" ? "instrumento" : "agencia";
  const chaveProduto = _mercadoAtivo === "primario" ? "indexador" : "produto";
  if (params.has(chaveTopo)) document.getElementById("bu-f-agencia").value = params.get(chaveTopo);
  if (params.has("valor_minimo")) document.getElementById("bu-f-valor-minimo").value = params.get("valor_minimo");
  if (params.has("regiao")) document.getElementById("bu-f-regiao").value = params.get("regiao");
  if (params.has(chaveProduto)) document.getElementById("bu-f-produto").value = params.get(chaveProduto);
  if (params.has("porte")) document.getElementById("bu-f-porte").value = params.get("porte");
  if (params.has("setor")) document.getElementById("bu-f-setor").value = params.get("setor");
  if (params.has("uf")) document.getElementById("bu-f-uf").value = params.get("uf");

  const q = (params.get("q") || "").trim();
  if (q) {
    document.getElementById("busca-input").value = q;
    // Mesma regra ja usada pro botao/Enter: so dispara a busca de verdade com
    // >=3 caracteres -- filtro sem query nao faz nada sozinho (ver runBusca).
    if (q.length >= 3) runBusca(q);
  }
}

// Remove tudo alem da 1a <option> (o "Todas"/"Todos" fixo do HTML) -- torna
// esta funcao segura de chamar de novo ao trocar de mercado (ver
// alternarMercado em common.js), sem duplicar opcao nem herdar optgroup do
// mercado anterior (setor/subsetor usam <optgroup>, removidos junto).
function _limparOpcoesBuscaFiltro(id) {
  const sel = document.getElementById(id);
  while (sel.children.length > 1) sel.removeChild(sel.lastElementChild);
}

async function _popularFiltrosBusca() {
  ["bu-f-agencia", "bu-f-produto", "bu-f-porte", "bu-f-uf", "bu-f-setor"].forEach(_limparOpcoesBuscaFiltro);
  try {
    const filtros = await fetchJSON(apiMercado("/api/filtros"));
    const fill = (id, values) => {
      const sel = document.getElementById(id);
      (values || []).filter(Boolean).forEach((v) => sel.appendChild(new Option(v, v)));
    };
    // #bu-f-agencia/#bu-f-produto: instrumentos/indexadores no Primario (ver
    // CLAUDE.md), agencias/produtos no Incentivado -- mesmo select reaproveitado.
    fill("bu-f-agencia", _mercadoAtivo === "primario" ? filtros.instrumentos : filtros.agencias);
    fill("bu-f-produto", _mercadoAtivo === "primario" ? filtros.indexadores : filtros.produtos);
    fill("bu-f-porte", filtros.portes);
    fill("bu-f-uf", filtros.ufs);

    // Setor: combina setor_bndes (4 categorias amplas) e subsetor_bndes (19, mais
    // granulares) NA MESMA lista (pedido do usuario) -- agrupados por <optgroup> so
    // pra ficar visualmente claro qual e qual, mas os dois viram o MESMO parametro
    // `setor` na busca (o backend testa contra as duas colunas, ver search_fts.py).
    // Mesma logica assumida pro Primario (setor_emissor/subsetor_emissor).
    const selSetor = document.getElementById("bu-f-setor");
    const grupoSetor = document.createElement("optgroup");
    grupoSetor.label = "Setor";
    (filtros.setores || []).filter(Boolean).forEach((v) => grupoSetor.appendChild(new Option(v, v)));
    const grupoSubsetor = document.createElement("optgroup");
    grupoSubsetor.label = "Subsetor";
    (filtros.subsetores || []).filter(Boolean).forEach((v) => grupoSubsetor.appendChild(new Option(v, v)));
    selSetor.appendChild(grupoSetor);
    selSetor.appendChild(grupoSubsetor);
  } catch (e) {
    // filtros da busca sao um extra -- se /api/{primario/}filtros falhar aqui, a
    // busca livre (sem filtro nenhum) continua funcionando normalmente.
  }
}

// Labels do filterbar PROPRIO da Busca que trocam de significado por mercado
// (ver #bu-label-agencia/#bu-label-produto em index.html) + placeholder do
// campo de busca livre. Chamada por common.js::_aplicarIdentidadeMercado()
// via `typeof` check.
function _aplicarRotulosMercadoBusca() {
  const primario = _mercadoAtivo === "primario";
  const labelAgencia = document.getElementById("bu-label-agencia");
  const labelProduto = document.getElementById("bu-label-produto");
  if (labelAgencia) labelAgencia.textContent = primario ? "Instrumento" : "Entidade";
  if (labelProduto) labelProduto.textContent = primario ? "Indexador" : "Tipo de linha";
  const input = document.getElementById("busca-input");
  if (input) {
    input.placeholder = primario
      ? "Descreva um emissor, instrumento ou indexador. Ex: debênture de infraestrutura indexada a IPCA no setor de energia"
      : "Descreva uma empresa ou setor. Ex: fintech de crédito para pequenas empresas do agro no Nordeste";
  }
}

async function runBusca(q) {
  await registrarHistoricoBusca(q);
  _sincronizarFiltrosBuscaNaURL(q);
  const container = document.getElementById("busca-resultado");
  container.innerHTML = '<p class="empty-state">Buscando operações parecidas...</p>';

  let data;
  try {
    if (window.BUSCA_IA_ATIVA) {
      // Modo por IA (embeddings) -- so ativo se MOTOR_BUSCA_IA=1 no servidor (ver
      // webapp/main.py). Calcula o vetor da query no navegador (transformers.js) e
      // manda pronto -- o servidor so faz numpy contra os vetores do corpus.
      const prep = await fetchJSON("/api/busca/preparar?" + qs({ q }));
      if (prep.erro) {
        container.innerHTML = `<p class="empty-state">${prep.erro}</p>`;
        return;
      }
      const vetor = await embutirQuery(prep.query_expandida, (info) => {
        if (info && info.status === "progress" && typeof info.progress === "number") {
          container.innerHTML = `<p class="empty-state">Baixando modelo de busca no seu navegador (${Math.round(info.progress)}%)...</p>`;
        }
      });
      data = await postJSON("/api/busca", { q, vetor });

      // A 1a passada pode vir com confianca baixa (nome de empresa/termo que a base
      // nao conhece, ex: "Quicksoft") -- tenta UMA 2a passada pesquisando `q` na web e
      // reembute com o texto descoberto. So substitui o resultado original se o novo
      // melhor_score vier melhor; qualquer falha aqui so mantem o resultado original.
      if (!data.erro && data.confianca_baixa) {
        try {
          const prepEnriquecido = await fetchJSON("/api/busca/preparar_enriquecido?" + qs({ q }), 10000);
          if (!prepEnriquecido.erro && prepEnriquecido.enriquecido_via_web && prepEnriquecido.query_expandida) {
            const vetorEnriquecido = await embutirQuery(prepEnriquecido.query_expandida);
            const dataEnriquecida = await postJSON("/api/busca", { q, vetor: vetorEnriquecido });
            if (!dataEnriquecida.erro && dataEnriquecida.melhor_score > data.melhor_score) {
              dataEnriquecida.query_original = q;
              dataEnriquecida.enriquecido_via_web = true;
              data = dataEnriquecida;
            }
          }
        } catch (e) {
          // enriquecimento opcional -- se falhar, so mantem o resultado original.
        }
      }
    } else {
      // Modo padrao: sem IA -- uma chamada so, full-text/trigram no servidor (ver
      // src/search_fts.py), sem calculo de vetor em lugar nenhum. Filtros
      // estruturados (entidade/valor minimo/regiao/tipo de linha) so se aplicam
      // aqui -- o modo por IA (embeddings) e legado/opcional, nao vale a pena
      // estender pra um caminho que nem roda por padrao.
      data = await fetchJSON(apiMercado("/api/busca") + "?" + qs({ q, ..._filtrosBusca() }));
    }
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao buscar. Tente novamente.</p>';
    return;
  }

  if (data.erro) {
    container.innerHTML = `<p class="empty-state">${data.erro}</p>`;
    return;
  }

  // 1x por busca (nunca 1 checagem por card) -- ver _carregarIdsSalvos acima.
  await _carregarIdsSalvos();
  renderResultados(data);
}

document.addEventListener("DOMContentLoaded", async () => {
  const input = document.getElementById("busca-input");
  document.getElementById("busca-btn").addEventListener("click", () => {
    if (input.value.trim().length >= 3) runBusca(input.value.trim());
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim().length >= 3) runBusca(input.value.trim());
  });
  // Digitar sem apertar Enter/clicar tambem deve refletir na URL depois que o
  // usuario para de digitar (debounce), mesmo sem uma busca nova ser executada.
  input.addEventListener("input", debounce(() => _sincronizarFiltrosBuscaNaURL(input.value.trim()), 400));

  await renderHistoricoBusca();
  await _popularFiltrosBusca();

  // Link compartilhado/F5: aplica os filtros (e dispara a busca, se tinha query)
  // ANTES so depois de popular as opcoes dos selects (bu-f-agencia/bu-f-produto
  // sao preenchidos dinamicamente por _popularFiltrosBusca acima) -- e so quando
  // a aba ativa na URL e de fato a Busca (ver _viewInicialDaURL).
  if (_viewInicialDaURL() === "busca") _aplicarFiltrosBuscaDaURL();

  // Mudar um filtro re-roda a busca atual (se ja tiver uma) -- filtro sem busca
  // nenhuma feita ainda nao faz nada sozinho, precisa de uma query pra filtrar.
  ["bu-f-agencia", "bu-f-valor-minimo", "bu-f-regiao", "bu-f-produto", "bu-f-porte", "bu-f-setor", "bu-f-uf"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      if (input.value.trim().length >= 3) runBusca(input.value.trim());
      else _sincronizarFiltrosBuscaNaURL(input.value.trim());
    });
  });
});
