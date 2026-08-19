// Aba Editais: chamadas publicas ABERTAS da FINEP -- filtros, dashboard de prazos,
// lista ordenada por urgencia, detalhe com resumo de elegibilidade por IA, e o
// endgame (descreva seu projeto -> quais editais parecem aplicaveis).

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

function renderResumoIA(container, resp) {
  if (resp.erro) {
    container.innerHTML = `<div class="resumo-ia-box">Não foi possível gerar o resumo agora: ${resp.erro}</div>`;
    return;
  }
  container.innerHTML = `<div class="resumo-ia-box">${resp.resumo}</div>`;
}

async function openEditalDetalhe(id) {
  document.getElementById("modal-title").textContent = "Detalhe do edital";
  document.getElementById("modal-ordenar").style.display = "none";
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
    <div class="detalhe-secao-titulo">Resumo de elegibilidade (IA local)</div>
    <div style="padding:14px;">
      <button class="resumo-ia-btn" id="btn-resumo-ia">Resumir elegibilidade com IA</button>
      <div id="resumo-ia-container"></div>
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

  const btnResumo = document.getElementById("btn-resumo-ia");
  const resumoContainer = document.getElementById("resumo-ia-container");
  btnResumo.addEventListener("click", async () => {
    btnResumo.disabled = true;
    btnResumo.textContent = "Buscando resumo...";
    try {
      // timeout generoso: no modo local, quando ha documento_chave_texto
      // (Regulamento+Anexo1), o prompt e bem maior e o proprio backend chama o
      // Ollama (OLLAMA_TIMEOUT_RESUMO); no modo hospedado essa chamada e rapida
      // (so cache ou o prompt pronto, sem gerar nada ainda).
      const resp = await fetchJSON(`/api/editais/${id}/resumo`, 310000);

      if (resp.hospedado && resp.precisa_gerar) {
        const disponivel = await verificarOllamaLocal();
        if (!disponivel) {
          renderResumoIA(resumoContainer, {
            erro: 'Ative a IA local primeiro -- clique em "Baixar IA local" no topo da página.',
          });
          return;
        }
        btnResumo.textContent = "Gerando com sua IA local (pode levar alguns minutos)...";
        let texto = null;
        try {
          texto = await gerarComOllamaLocal(resp.prompt, resp.modelo, resp.opcoes, 280000);
        } catch (e) {
          texto = null;
        }
        const textoFinal = (texto && texto.trim()) || resp.fallback;
        btnResumo.textContent = "Salvando para todo mundo...";
        const salvo = await postJSON(`/api/editais/${id}/resumo`, { resumo: textoFinal }, 15000);
        renderResumoIA(resumoContainer, salvo && !salvo.erro ? salvo : { resumo: textoFinal });
      } else {
        renderResumoIA(resumoContainer, resp);
      }
    } catch (e) {
      resumoContainer.innerHTML = '<div class="resumo-ia-box">Não foi possível gerar o resumo agora. Tente novamente.</div>';
    } finally {
      btnResumo.textContent = "Gerar novamente";
      btnResumo.disabled = false;
    }
  });
}

// ============ Endgame: descreva seu projeto -> editais aderentes ============
// Importante: a lista de editais so aparece DEPOIS que a IA revisa os candidatos e
// remove os que nao tem elegibilidade real (busca por embeddings sempre acha "algo"
// no corpus pequeno de editais abertos, mesmo quando nada realmente se aplica).

const ED_REFINO_DURACAO_ESTIMADA_MS = 30000;
const ED_LEITURA_DURACAO_ESTIMADA_MS = 20000;

function edIniciarProgresso(mensagem, duracaoEstimadaMs) {
  const inicio = Date.now();
  const fill = document.getElementById("ed-status-progress");
  const timer = document.getElementById("ed-status-timer");
  const msgEl = document.getElementById("ed-status-mensagem");
  if (!fill || !timer) return null;
  if (msgEl) msgEl.textContent = mensagem;
  fill.style.width = "0%";
  const interval = setInterval(() => {
    const decorrido = Date.now() - inicio;
    fill.style.width = Math.min(92, (decorrido / duracaoEstimadaMs) * 100) + "%";
    const s = Math.round(decorrido / 1000);
    timer.textContent = `${s}s decorridos · pode levar até 30-40s`;
  }, 300);
  return interval;
}

function edStatusBoxHTML(mensagem) {
  return `<div class="narrativa loading" id="ed-status-box">
    <div id="ed-status-mensagem">${mensagem}</div>
    <div class="progress-track"><div class="progress-fill" id="ed-status-progress"></div></div>
    <div class="progress-label" id="ed-status-timer">0s decorridos</div>
  </div>`;
}

// aplicarRefinoLocal() agora mora em common.js (reaproveitado por busca.js tambem).

async function runEditaisEndgame(q) {
  const container = document.getElementById("editais-endgame-resultado");
  container.innerHTML = edStatusBoxHTML("Buscando editais aderentes...");
  let progressInterval = edIniciarProgresso("Buscando editais aderentes...", ED_REFINO_DURACAO_ESTIMADA_MS);

  // Etapa 1 (rapida): acha os editais mais parecidos por embeddings. Modo hospedado
  // calcula o vetor da descricao NO NAVEGADOR (transformers.js, ver embeddings-
  // client.js, unico jeito de nao estourar os 512MB de RAM do free tier do servidor)
  // e manda pronto; modo local (desktop) continua igual a sempre (get_model() no
  // proprio backend).
  let buscaResp;
  try {
    if (window.MODO_HOSPEDADO) {
      const vetor = await embutirQuery(q, (info) => {
        if (info && info.status === "progress" && typeof info.progress === "number") {
          const msgEl = document.getElementById("ed-status-mensagem");
          if (msgEl) msgEl.textContent = `Baixando modelo de busca no seu navegador (${Math.round(info.progress)}%)...`;
        }
      });
      buscaResp = await postJSON("/api/editais/buscar", { q, vetor }, 60000);
    } else {
      buscaResp = await fetchJSON("/api/editais/buscar?" + qs({ q }), 60000);
    }
  } catch (e) {
    if (progressInterval) clearInterval(progressInterval);
    container.innerHTML = '<p class="empty-state">Erro ao buscar. Tente novamente.</p>';
    return;
  }
  if (buscaResp.erro) {
    if (progressInterval) clearInterval(progressInterval);
    container.innerHTML = `<p class="empty-state">${buscaResp.erro}</p>`;
    return;
  }

  // Etapa 2 (lenta, IA): remove falsos-positivos da busca rapida -- editais que so
  // bateram por semelhanca generica de texto mas nao tem elegibilidade real.
  const msgRefino = document.getElementById("ed-status-mensagem");
  if (msgRefino) msgRefino.textContent = "Analisando quais editais abertos realmente se aplicam...";

  let refino;
  try {
    if (window.MODO_HOSPEDADO) {
      refino = await postJSON("/api/editais/buscar/refinar", { q, resultados: buscaResp.resultados }, 100000);
    } else {
      refino = await fetchJSON("/api/editais/buscar/refinar?" + qs({ q }), 100000);
    }
  } catch (e) {
    if (progressInterval) clearInterval(progressInterval);
    container.innerHTML = '<p class="empty-state">Erro ao buscar. Tente novamente.</p>';
    return;
  }
  if (refino.erro) {
    if (progressInterval) clearInterval(progressInterval);
    container.innerHTML = `<p class="empty-state">${refino.erro}</p>`;
    return;
  }

  let resultados;
  let nOriginais;

  if (refino.hospedado) {
    // Modo hospedado: nao ha Ollama no servidor -- o navegador de quem esta
    // usando gera a filtragem com a propria IA local dela.
    const disponivel = await verificarOllamaLocal();
    if (!disponivel) {
      if (progressInterval) clearInterval(progressInterval);
      resultados = refino.resultados_sem_filtro || [];
      let html = resultados.length
        ? '<div class="confianca-baixa-aviso">⚠ Ative a IA local (botão no topo da página) para filtrar estes resultados por elegibilidade real -- por enquanto são só os mais parecidos por texto, sem revisão.</div>'
        : "";
      html += '<div id="editais-endgame-lista"></div>';
      container.innerHTML = html;
      const lista = document.getElementById("editais-endgame-lista");
      lista.innerHTML = resultados.length
        ? resultados.map(editalCardHTML).join("")
        : '<p class="empty-state">Nenhum edital aberto parece aderente a essa descrição.</p>';
      lista.querySelectorAll(".edital-card").forEach((card) => {
        card.addEventListener("click", () => openEditalDetalhe(card.dataset.id));
      });
      return;
    }
    nOriginais = (refino.candidatos_ids || []).length;
    let respostaTexto = null;
    if (refino.prompt) {
      try {
        respostaTexto = await gerarComOllamaLocal(refino.prompt, refino.modelo, refino.opcoes, 100000);
      } catch (e) {
        respostaTexto = null;
      }
    }
    const filtrados = respostaTexto
      ? aplicarRefinoLocal(refino.resultados_sem_filtro, refino.candidatos_ids, respostaTexto)
      : null;
    resultados = filtrados !== null ? filtrados : refino.resultados_sem_filtro;
  } else {
    resultados = refino.resultados || [];
    nOriginais = refino.n_originais || 0;
  }

  if (progressInterval) clearInterval(progressInterval);

  if (!resultados.length) {
    container.innerHTML = `<p class="empty-state">Nenhum edital aberto parece realmente aplicável a essa descrição${nOriginais ? ` -- a IA revisou ${nOriginais} candidato(s) encontrado(s) por similaridade e nenhum tinha elegibilidade real` : ""}.</p>`;
    return;
  }

  let html = edStatusBoxHTML("Gerando leitura de elegibilidade...");
  html += `<div id="editais-endgame-lista"></div>`;
  container.innerHTML = html;

  const lista = document.getElementById("editais-endgame-lista");
  lista.innerHTML = resultados.map(editalCardHTML).join("");
  lista.querySelectorAll(".edital-card").forEach((card) => {
    card.addEventListener("click", () => openEditalDetalhe(card.dataset.id));
  });

  progressInterval = edIniciarProgresso("Gerando leitura de elegibilidade...", ED_LEITURA_DURACAO_ESTIMADA_MS);
  try {
    const ids = resultados.map((r) => r.id).join(",");
    const leituraResp = await fetchJSON("/api/editais/buscar/leitura?" + qs({ q, ids }), 60000);
    let textoFinal;
    if (leituraResp.hospedado) {
      let gerado = null;
      if (leituraResp.prompt) {
        try {
          gerado = await gerarComOllamaLocal(leituraResp.prompt, leituraResp.modelo, leituraResp.opcoes, 100000);
        } catch (e) {
          gerado = null;
        }
      }
      textoFinal = (gerado && gerado.trim()) || leituraResp.fallback || "Não foi possível gerar a leitura.";
    } else {
      textoFinal = leituraResp.leitura || leituraResp.erro || "Não foi possível gerar a leitura.";
    }
    if (progressInterval) clearInterval(progressInterval);
    const box = document.getElementById("ed-status-box");
    if (box) {
      box.classList.remove("loading");
      box.innerHTML = `<div>${textoFinal}</div>`;
    }
  } catch (e) {
    if (progressInterval) clearInterval(progressInterval);
    const box = document.getElementById("ed-status-box");
    if (box) box.innerHTML = "<div>Não foi possível gerar a leitura em texto agora, mas os editais acima continuam válidos.</div>";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadEditaisFiltrosOpcoes();
  ["ed-f-situacao", "ed-f-empresa", "ed-f-tema", "ed-f-regiao", "ed-f-tipo"].forEach((id) => {
    document.getElementById(id).addEventListener("change", refreshEditais);
  });
  document.getElementById("ed-f-texto").addEventListener("keydown", (e) => {
    if (e.key === "Enter") refreshEditais();
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
