// Aba Busca: texto livre -> operacoes parecidas. Por padrao usa o motor sem IA
// (full-text/trigram, ver src/search_fts.py); so usa embeddings se o servidor tiver
// MOTOR_BUSCA_IA=1 ligado (ver window.BUSCA_IA_ATIVA, definido em common.js).

let ultimosResultados = [];

// Paginacao (2026-09-22): CLIENT-SIDE de proposito, nao no backend -- decisao medida ao
// vivo antes de implementar, nao suposta. /api/busca ja capa em 200 resultados (limite
// default de buscar_texto(), src/search_fts.py, nunca exposto pro caller hoje) e uma
// bateria real de queries (energia/hospital/software/ltda/transporte/banco) mediu payload
// de ~115-150KB e tempo de resposta de ~4,3-5,2s -- ou seja, o CUSTO real de uma busca e
// quase todo a query em si (tiers 1-3 fazem seq scan, piso de ~3-4s ja documentado em
// docs/motor-busca.md), nao o tamanho do payload nem o render no navegador. Paginar no
// backend (OFFSET) exigiria RE-EXECUTAR essa mesma query cara a cada troca de pagina --
// regressao clara do que temos hoje (1 fetch por busca, resto e so scroll). Alem disso, o
// "ordenar por" (data/valor/agencia) ja e 100% client-side e so funciona corretamente com
// o conjunto INTEIRO de resultados em memoria (senao cada pagina ordenaria so a propria
// fatia) -- mover so a paginacao pro backend sem mover a ordenacao junto quebraria essa
// feature existente. Paginar em memoria sobre `ultimosResultados` (ja limitado a 200)
// evita as duas armadilhas: troca de pagina e instantanea (zero fetch novo) e a
// ordenacao continua correta em qualquer pagina.
const BUSCA_RESULTADOS_POR_PAGINA = 20;
let buscaPaginaAtual = 1;

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
  const listaCompleta = ordenarResultados(ultimosResultados, criterio);
  const container = document.getElementById("busca-lista");
  const pagContainer = document.getElementById("busca-paginacao");

  if (!listaCompleta.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma operação parecida encontrada.</p>';
    if (pagContainer) pagContainer.innerHTML = "";
    return;
  }

  // Paginacao client-side (ver comentario no topo do arquivo) -- so recorta o array ja
  // ordenado, nunca refaz a busca. Clampa buscaPaginaAtual pro caso de a ordenacao/lista
  // ter mudado de tamanho (ex: nova busca com menos resultados que a pagina em que o
  // usuario estava).
  const totalPaginas = Math.max(1, Math.ceil(listaCompleta.length / BUSCA_RESULTADOS_POR_PAGINA));
  if (buscaPaginaAtual > totalPaginas) buscaPaginaAtual = totalPaginas;
  if (buscaPaginaAtual < 1) buscaPaginaAtual = 1;
  const inicio = (buscaPaginaAtual - 1) * BUSCA_RESULTADOS_POR_PAGINA;
  const lista = listaCompleta.slice(inicio, inicio + BUSCA_RESULTADOS_POR_PAGINA);

  container.innerHTML = lista
    .map((r) => `<div class="result-card" data-id="${r.id}">
        <div class="top-row">
          <span class="cliente">${r.cliente || "-"}</span>
          <span class="valor">${fmtBRLFull(r.valor_contratado)}</span>
        </div>
        <div class="meta">${r.agencia || "-"} · ${r.setor_bndes || "Não classificado"}${r.subsetor_bndes ? " · " + r.subsetor_bndes : ""}${r.segmento ? " · " + r.segmento : ""} · ${r.uf || "-"} · ${r.data_contratacao || "-"}</div>
        <div class="meta">${r.descricao_projeto ? r.descricao_projeto.slice(0, 160) : ""}</div>
        <div class="score">${typeof r.score === "number" ? `similaridade: ${(r.score * 100).toFixed(0)}%` : r.motivo || ""}</div>
      </div>`)
    .join("");

  container.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", () => openOperacaoDetalhe(card.dataset.id));
  });

  renderPaginacaoBusca(listaCompleta.length, totalPaginas);
}

// Controles de pagina (Anterior/1 2 3.../Proxima) -- cada clique so troca
// buscaPaginaAtual e chama renderListaResultados() de novo (nenhum fetch novo, ver
// comentario no topo do arquivo). Preserva automaticamente busca/filtros/ordenacao:
// nenhum desses 3 estados e tocado por uma troca de pagina.
function renderPaginacaoBusca(totalItens, totalPaginas) {
  const container = document.getElementById("busca-paginacao");
  if (!container) return;
  if (totalPaginas <= 1) {
    container.innerHTML = "";
    return;
  }

  const irPara = (p) => {
    if (p < 1 || p > totalPaginas || p === buscaPaginaAtual) return;
    buscaPaginaAtual = p;
    renderListaResultados();
    document.getElementById("busca-resultado").scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // Janela de numeros ao redor da pagina atual + primeira/ultima, com "..." nos
  // buracos -- com o teto atual de 200 resultados/20 por pagina (max 10 paginas) isso
  // hoje sempre mostra todas as paginas, mas continua correto se o limite do backend
  // crescer no futuro.
  const paginas = [];
  const janela = 1;
  for (let p = 1; p <= totalPaginas; p++) {
    if (p === 1 || p === totalPaginas || Math.abs(p - buscaPaginaAtual) <= janela) {
      paginas.push(p);
    } else if (paginas[paginas.length - 1] !== "...") {
      paginas.push("...");
    }
  }

  const estiloDesativado = "opacity:0.4; cursor:not-allowed;";
  const estiloInativa = "background:#fff; color:var(--navy); border:1px solid var(--border);";

  let html = `<span class="progress-label" style="align-self:center; margin-right:6px;">Página ${buscaPaginaAtual} de ${totalPaginas} (${fmtNum(totalItens)} resultados)</span>`;
  html += `<button class="acao-btn busca-pag-nav" data-p="${buscaPaginaAtual - 1}" style="padding:6px 12px; margin-top:0; ${buscaPaginaAtual === 1 ? estiloDesativado : ""}" ${buscaPaginaAtual === 1 ? "disabled" : ""}>‹ Anterior</button>`;
  html += paginas
    .map((p) => {
      if (p === "...") return '<span style="padding:0 4px; color:var(--text-muted);">…</span>';
      const ativa = p === buscaPaginaAtual;
      return `<button class="acao-btn busca-pag-nav" data-p="${p}" style="padding:6px 12px; margin-top:0; ${ativa ? "" : estiloInativa}" ${ativa ? "disabled" : ""}>${p}</button>`;
    })
    .join("");
  html += `<button class="acao-btn busca-pag-nav" data-p="${buscaPaginaAtual + 1}" style="padding:6px 12px; margin-top:0; ${buscaPaginaAtual === totalPaginas ? estiloDesativado : ""}" ${buscaPaginaAtual === totalPaginas ? "disabled" : ""}>Próxima ›</button>`;

  container.innerHTML = html;
  container.querySelectorAll(".busca-pag-nav").forEach((btn) => {
    btn.addEventListener("click", () => irPara(Number(btn.dataset.p)));
  });
}

function renderResultados(data) {
  ultimosResultados = data.resultados || [];
  buscaPaginaAtual = 1; // toda busca nova (texto/filtro) volta pra pagina 1
  let html = "";

  if (data.confianca_baixa) {
    html += `<div class="confianca-baixa-aviso">⚠ Não encontramos uma correspondência forte para "${data.query}" na base do BNDES/FINEP. Os resultados abaixo são os mais próximos disponíveis, mas com similaridade baixa (${Math.round(data.melhor_score * 100)}%).</div>`;
  }
  if (data.enriquecido_via_web) {
    html += `<div class="confianca-baixa-aviso">🔎 Resultados ajustados depois de pesquisar sobre "${data.query_original || data.query}" na web, para tentar entender melhor do que se trata.</div>`;
  }

  const prob = data.probabilidade_aprovacao;
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
  html += '<div id="busca-paginacao" style="display:flex; gap:6px; justify-content:center; align-items:center; margin-top:16px; flex-wrap:wrap;"></div>';

  document.getElementById("busca-resultado").innerHTML = html;
  document.getElementById("busca-ordenar").addEventListener("change", () => {
    buscaPaginaAtual = 1; // trocar o criterio de ordenacao tambem volta pra pagina 1
    renderListaResultados();
  });
  renderListaResultados();
}

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
    agencia: document.getElementById("bu-f-agencia").value,
    produto: document.getElementById("bu-f-produto").value,
  };
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
    agencia: document.getElementById("bu-f-agencia").value,
    produto: document.getElementById("bu-f-produto").value,
  };
  sincronizarFiltrosNaURL(params);
}

function _aplicarFiltrosBuscaDaURL() {
  const params = paramsDaURL();
  if (params.has("agencia")) document.getElementById("bu-f-agencia").value = params.get("agencia");
  if (params.has("valor_minimo")) document.getElementById("bu-f-valor-minimo").value = params.get("valor_minimo");
  if (params.has("regiao")) document.getElementById("bu-f-regiao").value = params.get("regiao");
  if (params.has("produto")) document.getElementById("bu-f-produto").value = params.get("produto");
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
// esta funcao segura de chamar de novo sem duplicar opcao.
function _limparOpcoesBuscaFiltro(id) {
  const sel = document.getElementById(id);
  while (sel.children.length > 1) sel.removeChild(sel.lastElementChild);
}

async function _popularFiltrosBusca() {
  ["bu-f-agencia", "bu-f-produto", "bu-f-porte", "bu-f-uf", "bu-f-setor"].forEach(_limparOpcoesBuscaFiltro);
  try {
    const filtros = await _fetchFiltrosCompartilhado();
    const fill = (id, values) => {
      const sel = document.getElementById(id);
      (values || []).filter(Boolean).forEach((v) => sel.appendChild(new Option(v, v)));
    };
    fill("bu-f-agencia", filtros.agencias);
    fill("bu-f-produto", filtros.produtos);
    fill("bu-f-porte", filtros.portes);
    fill("bu-f-uf", filtros.ufs);

    // Setor: combina setor_bndes (4 categorias amplas) e subsetor_bndes (19, mais
    // granulares) NA MESMA lista (pedido do usuario) -- agrupados por <optgroup> so
    // pra ficar visualmente claro qual e qual, mas os dois viram o MESMO parametro
    // `setor` na busca (o backend testa contra as duas colunas, ver search_fts.py).
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
    // filtros da busca sao um extra -- se /api/filtros falhar aqui, a
    // busca livre (sem filtro nenhum) continua funcionando normalmente.
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
      data = await fetchJSON("/api/busca?" + qs({ q, ..._filtrosBusca() }));
    }
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao buscar. Tente novamente.</p>';
    return;
  }

  if (data.erro) {
    container.innerHTML = `<p class="empty-state">${data.erro}</p>`;
    return;
  }

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
