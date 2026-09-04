// Aba Enriquecimento: historico de importacoes (planilhas oficiais baixadas
// automaticamente, ver refresh.py/refresh_editais.py), fila de registros pendentes de
// classificacao e correcao manual (ver src/unify.py::registrar_correcao_manual --
// prevalece sobre reclassificacoes automaticas futuras).

function fmtDataHora(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("pt-BR");
}

async function loadEnrImportacoes() {
  const container = document.getElementById("enr-importacoes");
  container.innerHTML = "Carregando...";
  let data;
  try {
    data = await fetchJSON("/api/enriquecimento/importacoes");
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao carregar histórico de importações.</p>';
    return;
  }

  const linhaTransacao = (r) => `<tr>
    <td>Transações (BNDES+FINEP)</td>
    <td>${fmtDataHora(r.started_at)}</td>
    <td>${fmtDataHora(r.finished_at)}</td>
    <td>${r.bndes_rows ?? "-"} / ${r.finep_credito_direto_rows ?? "-"} / ${r.finep_credito_descentralizado_rows ?? "-"}</td>
    <td>${r.operations_rows ?? "-"} (${r.setores_pendentes ?? 0} pendentes)</td>
    <td>${r.status || "-"}</td>
  </tr>`;
  const linhaEdital = (r) => `<tr>
    <td>Editais (FINEP)</td>
    <td>${fmtDataHora(r.started_at)}</td>
    <td>${fmtDataHora(r.finished_at)}</td>
    <td>${r.total_editais ?? "-"} totais</td>
    <td>${r.abertos ?? "-"} abertos</td>
    <td>${r.status || "-"}</td>
  </tr>`;

  const linhas = [
    ...data.transacoes.map(linhaTransacao),
    ...data.editais.map(linhaEdital),
  ];

  if (!linhas.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma importação registrada ainda.</p>';
    return;
  }

  container.innerHTML = `<div style="overflow-x:auto;"><table class="ops-table">
    <thead><tr><th>Processo</th><th>Iniciado em</th><th>Concluído em</th><th>Linhas (BNDES/Direto/Descentralizado)</th><th>Resultado</th><th>Status</th></tr></thead>
    <tbody>${linhas.join("")}</tbody>
  </table></div>`;
}

const CAMPOS_CORRECAO = [
  { valor: "setor_bndes", rotulo: "Setor" },
  { valor: "subsetor_bndes", rotulo: "Subsetor" },
  { valor: "segmento", rotulo: "Segmento" },
];

async function loadEnrPendentes() {
  const container = document.getElementById("enr-pendentes");
  container.innerHTML = "Carregando...";
  let data;
  try {
    data = await fetchJSON("/api/enriquecimento/pendentes?limit=30");
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao carregar registros pendentes.</p>';
    return;
  }

  if (!data.resultados.length) {
    container.innerHTML = '<p class="empty-state">Nenhum registro pendente de classificação no momento.</p>';
    return;
  }

  const opcoesCampo = CAMPOS_CORRECAO.map((c) => `<option value="${c.valor}">${c.rotulo}</option>`).join("");
  container.innerHTML = `<p class="progress-label" style="margin-bottom:10px;">${fmtNum(data.total)} registro(s) pendente(s) no total (mostrando os ${data.resultados.length} de maior valor)</p>` +
    data.resultados
      .map(
        (op) => `<div class="result-card" data-id="${op.id}" style="cursor:default;">
      <div class="top-row">
        <span class="cliente">${op.cliente || "Cliente não informado na planilha de origem"}</span>
        <span class="valor">${fmtBRLFull(op.valor_contratado)}</span>
      </div>
      <div class="meta">${op.agencia} · ${op.instrumento || "-"} · CNPJ: ${op.cnpj || "não informado pela fonte"} · ${op.uf || "-"} · ${op.data_contratacao || "-"}</div>
      <div class="meta">${op.descricao_projeto ? op.descricao_projeto.slice(0, 160) : ""}</div>
      <div class="correcao-form" style="display:flex; gap:6px; margin-top:8px; align-items:center;">
        <select class="header-select corr-campo" style="background:#fff; color:var(--navy); border-color:var(--border);">${opcoesCampo}</select>
        <input type="text" class="corr-valor" placeholder="Valor correto (ex: INDUSTRIA)" style="flex:1; padding:6px 10px; border:1px solid var(--border); border-radius:6px;">
        <button class="acao-btn corr-salvar" style="padding:6px 12px; font-size:13px;">Salvar correção</button>
      </div>
      <div class="meta corr-status"></div>
    </div>`
      )
      .join("");

  container.querySelectorAll(".result-card").forEach((card) => {
    const opId = card.dataset.id;
    card.querySelector(".corr-salvar").addEventListener("click", async () => {
      const campo = card.querySelector(".corr-campo").value;
      const valor_novo = card.querySelector(".corr-valor").value.trim();
      const status = card.querySelector(".corr-status");
      if (!valor_novo) {
        status.textContent = "Digite um valor antes de salvar.";
        return;
      }
      status.textContent = "Salvando...";
      try {
        const resp = await postJSON("/api/enriquecimento/corrigir", { operation_id: Number(opId), campo, valor_novo });
        if (resp.erro) {
          status.textContent = `Erro: ${resp.erro}`;
        } else {
          status.textContent = "Correção salva -- prevalecerá sobre reclassificações automáticas futuras.";
          loadEnrCorrecoes();
        }
      } catch (e) {
        status.textContent = "Erro ao salvar a correção. Tente novamente.";
      }
    });
  });
}

async function loadEnrCorrecoes() {
  const container = document.getElementById("enr-correcoes");
  container.innerHTML = "Carregando...";
  let data;
  try {
    data = await fetchJSON("/api/enriquecimento/correcoes");
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Erro ao carregar correções manuais.</p>';
    return;
  }

  if (!data.resultados.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma correção manual registrada ainda.</p>';
    return;
  }

  container.innerHTML = `<div style="overflow-x:auto;"><table class="ops-table">
    <thead><tr><th>Cliente</th><th>Campo</th><th>Valor anterior</th><th>Valor novo</th><th>Quando</th><th>Status</th></tr></thead>
    <tbody>${data.resultados
      .map(
        (c) => `<tr>
      <td>${c.cliente || "-"} (op. ${c.operation_id})</td>
      <td>${c.campo}</td>
      <td>${c.valor_anterior || "-"}</td>
      <td>${c.valor_novo}</td>
      <td>${fmtDataHora(c.criado_em)}</td>
      <td>${c.ativa ? "Ativa" : "Substituída"}</td>
    </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    if (btn.dataset.view === "enriquecimento") {
      btn.addEventListener(
        "click",
        () => {
          loadEnrImportacoes();
          loadEnrPendentes();
          loadEnrCorrecoes();
        },
        { once: true }
      );
    }
  });
});
