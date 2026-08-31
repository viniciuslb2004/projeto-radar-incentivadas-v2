// Aba Busca: texto livre -> operacoes parecidas (rapido) + revisao por IA + leitura de tendencia (mais lentas).

const REFINO_DURACAO_ESTIMADA_MS = 25000; // estimativa para a barra de progresso (Ollama em CPU local)
const NARRATIVA_DURACAO_ESTIMADA_MS = 25000;

let ultimosResultados = [];

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
        <div class="score">similaridade: ${(r.score * 100).toFixed(0)}%</div>
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

  html += `<div class="narrativa loading" id="status-box">
    <div id="status-mensagem">Revisando resultados com IA local (Ollama, roda no seu computador)...</div>
    <div class="progress-track"><div class="progress-fill" id="status-progress"></div></div>
    <div class="progress-label" id="status-timer">0s decorridos · pode levar até 30-40s</div>
  </div>`;

  html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:10px;">
    <span class="progress-label" id="busca-contagem">${fmtNum(ultimosResultados.length)} operações parecidas encontradas</span>
    <div style="display:flex; gap:8px; align-items:center;">
      <button id="busca-exportar-btn" class="resumo-ia-btn" style="padding:6px 12px; font-size:13px;">Exportar CSV</button>
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
    ]);
  });
  renderListaResultados();
}

// Barra de progresso generica (usada tanto na etapa de revisao quanto na de narrativa) --
// nunca deixa o usuario sem nenhum feedback de que algo esta acontecendo, mesmo quando
// a etapa anterior ainda esta em andamento.
function iniciarProgresso(mensagem, duracaoEstimadaMs) {
  const inicio = Date.now();
  const msgEl = document.getElementById("status-mensagem");
  const fill = document.getElementById("status-progress");
  const timer = document.getElementById("status-timer");
  if (!fill || !timer) return null;

  if (msgEl) msgEl.textContent = mensagem;
  fill.style.width = "0%";

  const interval = setInterval(() => {
    const decorrido = Date.now() - inicio;
    const pct = Math.min(92, (decorrido / duracaoEstimadaMs) * 100);
    fill.style.width = pct + "%";
    const s = Math.round(decorrido / 1000);
    timer.textContent = s < 60 ? `${s}s decorridos · pode levar até 30-40s` : `${s}s decorridos · em CPU local isso pode demorar; os resultados acima já são válidos`;
  }, 300);

  return interval;
}

function finalizarProgresso() {
  const fill = document.getElementById("status-progress");
  if (fill) fill.style.width = "100%";
}

function finalizarNarrativa(texto) {
  const box = document.getElementById("status-box");
  if (!box) return;
  box.classList.remove("loading");
  box.innerHTML = `<div>${texto}</div>`;
}

// Modo HOSPEDADO: revisao (2a etapa) via o Ollama local de quem esta usando -- o
// servidor so monta o prompt (montar_prompt_refino em search.py), a filtragem do
// JSON e a busca por "termos adicionais" acontecem aqui no navegador.
async function refinarComIAHospedado(data) {
  const contagem = document.getElementById("busca-contagem");
  try {
    const prep = await postJSON("/api/busca/refinar", { query_expandida: data.query_expandida, resultados: ultimosResultados }, 30000);
    if (prep.erro || !prep.prompt) {
      if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas`;
      return;
    }
    const disponivel = await verificarOllamaLocal();
    if (!disponivel) {
      if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas <span class="hint">(ative a IA local para revisar por relevância real)</span>`;
      return;
    }

    let respostaTexto = null;
    try {
      respostaTexto = await gerarComOllamaLocal(prep.prompt, prep.modelo, prep.opcoes, 220000);
    } catch (e) {
      respostaTexto = null;
    }
    if (!respostaTexto) {
      if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas`;
      return;
    }

    const refinados = aplicarRefinoLocal(ultimosResultados, prep.candidatos_ids, respostaTexto);
    if (refinados === null) {
      if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas`;
      return;
    }
    const candidatosSet = new Set(prep.candidatos_ids || []);
    const restante = ultimosResultados.filter((r) => !candidatosSet.has(r.id));
    const nRemovidos = (prep.candidatos_ids || []).length - refinados.length;

    // Termos adicionais: cada um precisa de um vetor calculado no navegador tambem.
    const termosAdicionais = extrairTermosAdicionaisLocal(respostaTexto);
    let adicionados = [];
    const jaIncluidosIds = ultimosResultados.map((r) => r.id);
    for (const termo of termosAdicionais) {
      try {
        const vetorTermo = await embutirQuery(termo);
        const resp = await postJSON(
          "/api/busca/termo",
          { termo, vetor: vetorTermo, ja_incluidos: jaIncluidosIds.concat(adicionados.map((a) => a.id)) },
          15000
        );
        if (resp.resultados) adicionados = adicionados.concat(resp.resultados);
      } catch (e) {
        // enriquecimento opcional -- se falhar, so nao adiciona esses extras.
      }
    }

    ultimosResultados = refinados.concat(adicionados).concat(restante);
    renderListaResultados();
    const partes = [`${fmtNum(ultimosResultados.length)} operações parecidas encontradas`];
    const ajustes = [];
    if (nRemovidos > 0) ajustes.push(`${nRemovidos} removidas por não serem relevantes`);
    if (adicionados.length) ajustes.push(`${adicionados.length} adicionadas pela IA`);
    if (ajustes.length && contagem) {
      contagem.innerHTML = `${partes[0]} <span class="hint" style="color:var(--positive);">(revisado pela sua IA local: ${ajustes.join(", ")})</span>`;
    } else if (contagem) {
      contagem.innerHTML = `${partes[0]} <span class="hint">(revisado pela sua IA local, sem alterações)</span>`;
    }
  } catch (e) {
    if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas`;
  }
}

// Modo LOCAL (desktop): igual a sempre -- o proprio backend chama o Ollama.
async function refinarComIA(q) {
  const contagem = document.getElementById("busca-contagem");
  try {
    const refino = await fetchJSON("/api/busca/refinar?" + qs({ q }), 220000);
    if (refino.erro || !refino.refinado) {
      if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas`;
      return;
    }
    ultimosResultados = refino.resultados || ultimosResultados;
    renderListaResultados();
    const partes = [`${fmtNum(ultimosResultados.length)} operações parecidas encontradas`];
    const ajustes = [];
    if (refino.n_removidos) ajustes.push(`${refino.n_removidos} removidas por não serem relevantes`);
    if (refino.n_adicionados) ajustes.push(`${refino.n_adicionados} adicionadas pela IA`);
    if (ajustes.length && contagem) {
      contagem.innerHTML = `${partes[0]} <span class="hint" style="color:var(--positive);">(revisado pela IA: ${ajustes.join(", ")})</span>`;
    } else if (contagem) {
      contagem.innerHTML = `${partes[0]} <span class="hint">(revisado pela IA, sem alterações)</span>`;
    }
  } catch (e) {
    if (contagem) contagem.innerHTML = `${fmtNum(ultimosResultados.length)} operações parecidas encontradas`;
  }
}

// Modo HOSPEDADO: narrativa via o Ollama local de quem esta usando -- o servidor so
// monta o prompt (montar_prompt_narrativa em search.py).
async function narrativaComIAHospedado(data) {
  try {
    const prep = await postJSON(
      "/api/busca/narrativa",
      {
        query_expandida: data.query_expandida,
        tendencia_segmento: data.tendencia_segmento,
        tendencia_setor: data.tendencia_setor,
        resultados: ultimosResultados,
        confianca_baixa: data.confianca_baixa,
      },
      30000
    );
    if (prep.erro) return prep.erro;
    if (!prep.prompt) return prep.fallback || "Não foi possível gerar a análise.";
    const disponivel = await verificarOllamaLocal();
    if (!disponivel) return prep.fallback || 'Ative a IA local (botão no topo da página) para gerar uma leitura personalizada.';
    try {
      const texto = await gerarComOllamaLocal(prep.prompt, prep.modelo, prep.opcoes, 220000);
      return (texto && texto.trim()) || prep.fallback;
    } catch (e) {
      return prep.fallback || "Não foi possível gerar a análise agora.";
    }
  } catch (e) {
    return "Não foi possível gerar a análise em texto agora, mas os resultados acima continuam válidos.";
  }
}

async function runBusca(q) {
  const container = document.getElementById("busca-resultado");
  container.innerHTML = '<p class="empty-state">Buscando operações parecidas...</p>';

  let data;
  try {
    if (window.MODO_HOSPEDADO) {
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
    } else {
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

  // Modo HOSPEDADO: a 1a passada ja veio com confianca baixa (nome de empresa/termo
  // que a base nao conhece, ex: "Quicksoft") -- tenta UMA 2a passada pesquisando `q` na
  // web (equivalente ao que buscar_rapido() ja faz sozinho no modo local, ver
  // search.py) e reembute com o texto descoberto. So substitui o resultado original se
  // o novo melhor_score vier melhor; qualquer falha aqui so mantem o resultado original
  // (nunca deixa a busca sem resposta por causa de um enriquecimento que nao deu certo).
  if (window.MODO_HOSPEDADO && data.confianca_baixa) {
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

  renderResultados(data);

  // Etapa 2 (lenta, Ollama): revisa a lista -- remove falsos-positivos, reordena por
  // relevancia real e acha operacoes correlatas que a busca rapida deixou passar.
  let progressInterval = iniciarProgresso("Revisando resultados com IA local (Ollama, roda no seu computador)...", REFINO_DURACAO_ESTIMADA_MS);
  if (window.MODO_HOSPEDADO) {
    await refinarComIAHospedado(data);
  } else {
    await refinarComIA(q);
  }
  if (progressInterval) clearInterval(progressInterval);
  finalizarProgresso();

  // Etapa 3 (lenta, Ollama): gera a leitura em texto.
  progressInterval = iniciarProgresso("Gerando análise com IA local (Ollama, roda no seu computador)...", NARRATIVA_DURACAO_ESTIMADA_MS);
  try {
    let textoFinal;
    if (window.MODO_HOSPEDADO) {
      textoFinal = await narrativaComIAHospedado(data);
    } else {
      const narrativaResp = await fetchJSON("/api/busca/narrativa?" + qs({ q }), 150000);
      textoFinal = narrativaResp.narrativa || narrativaResp.erro || "Não foi possível gerar a análise.";
    }
    if (progressInterval) clearInterval(progressInterval);
    finalizarProgresso();
    finalizarNarrativa(textoFinal);
  } catch (e) {
    if (progressInterval) clearInterval(progressInterval);
    finalizarNarrativa("Não foi possível gerar a análise em texto agora, mas os resultados acima continuam válidos.");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("busca-input");
  document.getElementById("busca-btn").addEventListener("click", () => {
    if (input.value.trim().length >= 3) runBusca(input.value.trim());
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim().length >= 3) runBusca(input.value.trim());
  });
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.q;
      runBusca(chip.dataset.q);
    });
  });
});
