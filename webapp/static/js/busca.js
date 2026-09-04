// Aba Busca: texto livre -> operacoes parecidas. Por padrao usa o motor sem IA
// (full-text/trigram, ver src/search_fts.py); so usa embeddings se o servidor tiver
// MOTOR_BUSCA_IA=1 ligado (ver window.BUSCA_IA_ATIVA, definido em common.js).

let ultimosResultados = [];

// Historico de buscas: pessoal e temporario (so no navegador da propria pessoa,
// via localStorage -- nunca vai pro servidor). Substitui os chips de exemplo
// fixos que existiam antes (pedido do usuario).
const BUSCA_HISTORICO_KEY = "radar_busca_historico";
const BUSCA_HISTORICO_MAX = 8;

function carregarHistoricoBusca() {
  try {
    const bruto = localStorage.getItem(BUSCA_HISTORICO_KEY);
    const lista = bruto ? JSON.parse(bruto) : [];
    return Array.isArray(lista) ? lista : [];
  } catch (e) {
    return [];
  }
}

function registrarHistoricoBusca(q) {
  try {
    const atual = carregarHistoricoBusca().filter((item) => item.toLowerCase() !== q.toLowerCase());
    atual.unshift(q);
    localStorage.setItem(BUSCA_HISTORICO_KEY, JSON.stringify(atual.slice(0, BUSCA_HISTORICO_MAX)));
  } catch (e) {
    // localStorage indisponivel (aba privada, storage bloqueado) -- historico so nao aparece.
  }
  renderHistoricoBusca();
}

function renderHistoricoBusca() {
  const container = document.getElementById("busca-historico");
  const input = document.getElementById("busca-input");
  const historico = carregarHistoricoBusca();

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
    limpar.addEventListener("click", () => {
      try {
        localStorage.removeItem(BUSCA_HISTORICO_KEY);
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

  container.innerHTML = lista
    .map(
      (r) => `<div class="result-card" data-id="${r.id}">
        <div class="top-row">
          <span class="cliente">${r.cliente || "-"}</span>
          <span class="valor">${fmtBRLFull(r.valor_contratado)}</span>
        </div>
        <div class="meta">${r.agencia} · ${r.setor_bndes || "Não classificado"}${r.subsetor_bndes ? " · " + r.subsetor_bndes : ""}${r.segmento ? " · " + r.segmento : ""} · ${r.uf || "-"} · ${r.data_contratacao || "-"}</div>
        <div class="meta">${r.descricao_projeto ? r.descricao_projeto.slice(0, 160) : ""}</div>
        <div class="score">${typeof r.score === "number" ? `similaridade: ${(r.score * 100).toFixed(0)}%` : r.motivo || ""}</div>
      </div>`
    )
    .join("");

  container.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", () => openOperacaoDetalhe(card.dataset.id));
  });
}

function renderResultados(data) {
  ultimosResultados = data.resultados || [];
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
      <button id="busca-exportar-btn" class="acao-btn" style="padding:6px 12px; font-size:13px;">Exportar CSV</button>
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
  document.getElementById("busca-exportar-btn").addEventListener("click", () => {
    exportarCSV(`busca-${(data.query || "resultado").replace(/[^a-z0-9]+/gi, "-")}.csv`, ultimosResultados, [
      { chave: "cliente", rotulo: "Cliente" },
      { chave: "cnpj", rotulo: "CNPJ" },
      { chave: "agencia", rotulo: "Agência" },
      { chave: "setor_bndes", rotulo: "Setor" },
      { chave: "subsetor_bndes", rotulo: "Subsetor" },
      { chave: "segmento", rotulo: "Segmento" },
      { chave: "uf", rotulo: "UF" },
      { chave: "data_contratacao", rotulo: "Data" },
      { chave: "valor_contratado", rotulo: "Valor contratado" },
      { chave: "valor_desembolsado", rotulo: "Valor desembolsado" },
      { chave: "descricao_projeto", rotulo: "Descrição do projeto" },
      { chave: "score", rotulo: "Similaridade" },
      { chave: "motivo", rotulo: "Motivo da correspondência" },
    ]);
  });
  renderListaResultados();
}

async function runBusca(q) {
  registrarHistoricoBusca(q);
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
      // src/search_fts.py), sem calculo de vetor em lugar nenhum.
      data = await fetchJSON("/api/busca?" + qs({ q }));
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

document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("busca-input");
  document.getElementById("busca-btn").addEventListener("click", () => {
    if (input.value.trim().length >= 3) runBusca(input.value.trim());
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim().length >= 3) runBusca(input.value.trim());
  });
  renderHistoricoBusca();
});
