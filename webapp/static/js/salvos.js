// Aba "Transações Salvas": operações favoritadas (com nota pessoal) + histórico de
// busca gravado no SERVIDOR por usuário logado (ver webapp/salvos.py). Ao contrário
// do histórico em localStorage da aba Busca (que continua existindo em paralelo,
// como fallback pra quando ninguém está logado -- ver busca.js/CLAUDE.md), esta
// página só faz sentido com uma conta de verdade: sem sessão válida, /api/salvos
// devolve 401 e a página mostra um estado vazio pedindo login.

let _ultimoSalvosData = null;

function _fmtDataHora(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch (e) {
    return iso;
  }
}

function renderResumoSalvos(resumo) {
  document.getElementById("salvos-resumo").innerHTML =
    kpiCard("Operações salvas", fmtNum(resumo.total_operacoes)) +
    kpiCard("Valor contratado (total)", fmtBRL(resumo.valor_total));
}

function renderOperacoesSalvas(operacoes) {
  const container = document.getElementById("salvos-operacoes-lista");
  if (!operacoes.length) {
    container.innerHTML = '<p class="empty-state">Você ainda não salvou nenhuma operação. Abra o detalhe de uma operação (Busca, Consolidado etc.) e clique em "☆ Salvar".</p>';
    return;
  }

  container.innerHTML = operacoes
    .map(
      (op) => `<div class="result-card" data-op-id="${op.operation_id}">
        <div class="top-row">
          <span class="cliente">${op.cliente || "-"}</span>
          <span class="valor">${fmtBRLFull(op.valor_contratado)}</span>
        </div>
        <div class="meta">${op.agencia} · ${op.setor_bndes || "Não classificado"}${op.subsetor_bndes ? " · " + op.subsetor_bndes : ""} · ${op.uf || "-"} · ${op.data_contratacao || "-"}</div>
        <div class="meta">Salvo em ${_fmtDataHora(op.salvo_em)}</div>
        <textarea class="salvos-nota" data-op-id="${op.operation_id}" placeholder="Nota pessoal (só você vê)...">${op.nota ? op.nota.replace(/</g, "&lt;") : ""}</textarea>
        <div style="display:flex; justify-content:flex-end; margin-top:6px;">
          <button class="acao-btn salvos-remover-btn" data-op-id="${op.operation_id}" style="background:transparent; color:var(--text-muted); border:1px solid var(--border);">Remover</button>
        </div>
      </div>`
    )
    .join("");

  container.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("textarea") || e.target.closest("button")) return;
      openOperacaoDetalhe(card.dataset.opId);
    });
  });

  container.querySelectorAll(".salvos-nota").forEach((textarea) => {
    textarea.addEventListener("click", (e) => e.stopPropagation());
    textarea.addEventListener("blur", async () => {
      try {
        await patchJSON(`/api/salvos/operacoes/${textarea.dataset.opId}`, { nota: textarea.value });
      } catch (e) {
        alert("Não foi possível salvar a nota agora.");
      }
    });
  });

  container.querySelectorAll(".salvos-remover-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Remover esta operação das salvas?")) return;
      try {
        await deleteJSON(`/api/salvos/operacoes/${btn.dataset.opId}`);
        recarregarSalvos();
      } catch (e2) {
        alert("Não foi possível remover agora.");
      }
    });
  });
}

function renderHistoricoSalvos(historico) {
  const container = document.getElementById("salvos-historico-lista");
  if (!historico.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma busca registrada ainda.</p>';
    return;
  }

  container.innerHTML =
    '<ul class="clickable-list">' +
    historico
      .map(
        (h) => `<li data-hist-id="${h.id}">
          <span>${h.fixada ? "📌 " : ""}${h.query}</span>
          <span style="display:flex; gap:6px;">
            <button class="acao-btn salvos-hist-reexecutar" data-q="${h.query.replace(/"/g, "&quot;")}" style="padding:4px 10px; font-size:11px; margin:0;">Buscar de novo</button>
            <button class="acao-btn salvos-hist-fixar" data-hist-id="${h.id}" data-fixada="${h.fixada}" style="padding:4px 10px; font-size:11px; margin:0; background:transparent; color:var(--navy); border:1px solid var(--border);">${h.fixada ? "Desafixar" : "Fixar"}</button>
            <button class="acao-btn salvos-hist-remover" data-hist-id="${h.id}" style="padding:4px 10px; font-size:11px; margin:0; background:transparent; color:var(--text-muted); border:1px solid var(--border);">Remover</button>
          </span>
        </li>`
      )
      .join("") +
    "</ul>";

  container.querySelectorAll(".salvos-hist-reexecutar").forEach((btn) => {
    btn.addEventListener("click", () => {
      _ativarView("busca", true);
      const input = document.getElementById("busca-input");
      input.value = btn.dataset.q;
      runBusca(btn.dataset.q);
    });
  });

  container.querySelectorAll(".salvos-hist-fixar").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await postJSON(`/api/salvos/historico/${btn.dataset.histId}/fixar`, { fixada: btn.dataset.fixada !== "true" });
        recarregarSalvos();
      } catch (e) {
        alert("Não foi possível atualizar agora.");
      }
    });
  });

  container.querySelectorAll(".salvos-hist-remover").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await deleteJSON(`/api/salvos/historico/${btn.dataset.histId}`);
        recarregarSalvos();
      } catch (e) {
        alert("Não foi possível remover agora.");
      }
    });
  });
}

async function recarregarSalvos() {
  const semLogin = document.getElementById("salvos-sem-login");
  const conteudo = document.getElementById("salvos-conteudo");
  try {
    const data = await fetchJSON("/api/salvos");
    _ultimoSalvosData = data;
    semLogin.classList.add("hidden");
    conteudo.classList.remove("hidden");
    renderResumoSalvos(data.resumo);
    renderOperacoesSalvas(data.operacoes);
    renderHistoricoSalvos(data.historico);
  } catch (e) {
    // Sem sessao valida (ErroAutenticacao, 401) -- pagina so faz sentido logado.
    semLogin.classList.remove("hidden");
    conteudo.classList.add("hidden");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("salvos-exportar-btn").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    const textoOriginal = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Gerando...";
    try {
      const resp = await fetch(_urlCompleta("/api/salvos/exportar"), { method: "POST", credentials: "include" });
      if (!resp.ok) throw new Error("falha ao gerar excel");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "transacoes-salvas.xlsx";
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

  document.getElementById("salvos-historico-limpar-btn").addEventListener("click", async () => {
    if (!confirm("Limpar todo o histórico não fixado?")) return;
    try {
      await deleteJSON("/api/salvos/historico");
      recarregarSalvos();
    } catch (e) {
      alert("Não foi possível limpar agora.");
    }
  });

  // So busca de verdade quando a aba fica ativa (nao no carregamento da pagina
  // inteira) -- diferente das outras abas (busca.js/linhas.js), que carregam filtros
  // leves sempre: aqui o dado ja depende de sessao valida, entao adia pra quando a
  // pessoa realmente abre a aba (clique OU link direto/F5 -- ver _viewInicialDaURL).
  document.querySelectorAll('.tab-btn[data-view="salvos"]').forEach((btn) => {
    btn.addEventListener("click", recarregarSalvos);
  });
  if (_viewInicialDaURL() === "salvos") recarregarSalvos();
});
