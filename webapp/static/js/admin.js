// Painel de admin -- JS proprio, NAO reaproveita common.js do site publico (auth
// separada, sem sessionStorage/Authorization header: aqui a sessao vive num cookie
// httponly validado no backend, ver webapp/admin/auth.py).
(function () {
  "use strict";

  const API = "/admin/api";

  const loginView = document.getElementById("admin-login-view");
  const painelView = document.getElementById("admin-painel-view");
  const loginForm = document.getElementById("admin-login-card");
  const loginErro = document.getElementById("admin-login-erro");
  const loginBtn = document.getElementById("admin-login-btn");
  const usuarioLogadoEl = document.getElementById("admin-usuario-logado");
  const logoutBtn = document.getElementById("admin-logout-btn");
  const buscaInput = document.getElementById("admin-busca-usuario");
  const usuariosTbody = document.getElementById("admin-usuarios-tbody");
  const cardsEl = document.getElementById("admin-cards");

  async function apiFetch(path, options) {
    const resp = await fetch(API + path, Object.assign({ credentials: "same-origin" }, options));
    if (resp.status === 401) {
      mostrarLogin();
      throw new Error("nao autenticado");
    }
    return resp;
  }

  function mostrarLogin() {
    painelView.classList.add("hidden");
    loginView.classList.remove("hidden");
  }

  function mostrarPainel() {
    loginView.classList.add("hidden");
    painelView.classList.remove("hidden");
  }

  function formatarData(iso) {
    if (!iso) return "--";
    try {
      return new Date(iso).toLocaleString("pt-BR");
    } catch (e) {
      return iso;
    }
  }

  function renderRefresh(elId, dado, camposLinhas) {
    const el = document.getElementById(elId);
    if (!dado) {
      el.innerHTML = '<div class="admin-refresh-vazio">Nenhuma execução registrada ainda.</div>';
      return;
    }
    const statusClasse = (dado.status || "").toLowerCase().includes("erro") ? "status-erro" : "status-ok";
    let html = `<div>Status: <span class="${statusClasse}">${dado.status || "--"}</span></div>`;
    html += `<div>Iniciado em: ${formatarData(dado.started_at)}</div>`;
    html += `<div>Concluído em: ${formatarData(dado.finished_at)}</div>`;
    camposLinhas.forEach(function (c) {
      html += `<div>${c.rotulo}: ${dado[c.campo] != null ? dado[c.campo] : "--"}</div>`;
    });
    if (dado.detalhe) {
      html += `<div>Detalhe: ${dado.detalhe}</div>`;
    }
    el.innerHTML = html;
  }

  function renderCards(dashboard) {
    const itens = [
      { rotulo: "Usuários do painel", valor: dashboard.total_usuarios },
      { rotulo: "Operações (BNDES + FINEP)", valor: dashboard.total_operacoes },
      { rotulo: "Linhas incentivadas", valor: dashboard.total_linhas_incentivadas },
      { rotulo: "Editais FINEP", valor: dashboard.total_editais },
      { rotulo: "CNPJs pendentes de enriquecimento", valor: dashboard.pendentes_enriquecimento },
    ];
    cardsEl.innerHTML = itens
      .map(
        (i) =>
          `<div class="admin-card"><div class="valor">${i.valor != null ? i.valor : "--"}</div><div class="rotulo">${i.rotulo}</div></div>`
      )
      .join("");
  }

  async function carregarDashboard() {
    const resp = await apiFetch("/dashboard");
    const dado = await resp.json();
    renderCards(dado);
    renderRefresh("admin-refresh-operacoes", dado.refresh_operacoes, [
      { campo: "operations_rows", rotulo: "Operações na base" },
      { campo: "setores_pendentes", rotulo: "Setores pendentes" },
    ]);
    renderRefresh("admin-refresh-editais", dado.refresh_editais, [
      { campo: "total_editais", rotulo: "Total de editais" },
      { campo: "abertos", rotulo: "Abertos" },
    ]);
  }

  function renderUsuarios(usuarios) {
    if (!usuarios.length) {
      usuariosTbody.innerHTML = '<tr><td colspan="4">Nenhum usuário encontrado.</td></tr>';
      return;
    }
    usuariosTbody.innerHTML = usuarios
      .map(function (u) {
        const pillClasse = u.ativo ? "ativo" : "inativo";
        const pillTexto = u.ativo ? "Ativo" : "Inativo";
        const acaoTexto = u.ativo ? "Desativar" : "Ativar";
        return `<tr>
          <td>${u.username}</td>
          <td><span class="admin-pill ${pillClasse}">${pillTexto}</span></td>
          <td>${formatarData(u.criado_em)}</td>
          <td><button class="admin-toggle-btn" data-id="${u.id}" data-ativo="${u.ativo}">${acaoTexto}</button></td>
        </tr>`;
      })
      .join("");
  }

  async function carregarUsuarios(q) {
    const resp = await apiFetch("/usuarios?q=" + encodeURIComponent(q || ""));
    const dado = await resp.json();
    renderUsuarios(dado.usuarios);
  }

  usuariosTbody.addEventListener("click", async function (ev) {
    const btn = ev.target.closest(".admin-toggle-btn");
    if (!btn) return;
    const id = btn.dataset.id;
    const ativoAtual = btn.dataset.ativo === "true";
    btn.disabled = true;
    try {
      await apiFetch(`/usuarios/${id}/ativo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ativo: !ativoAtual }),
      });
      await carregarUsuarios(buscaInput.value);
    } finally {
      btn.disabled = false;
    }
  });

  let buscaTimeout = null;
  buscaInput.addEventListener("input", function () {
    clearTimeout(buscaTimeout);
    buscaTimeout = setTimeout(function () {
      carregarUsuarios(buscaInput.value);
    }, 250);
  });

  async function iniciarPainel(username) {
    usuarioLogadoEl.textContent = username;
    mostrarPainel();
    await Promise.all([carregarDashboard(), carregarUsuarios("")]);
  }

  loginForm.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    loginErro.classList.add("hidden");
    loginBtn.disabled = true;
    const username = document.getElementById("admin-login-usuario").value.trim();
    const password = document.getElementById("admin-login-senha").value;
    try {
      const resp = await fetch(API + "/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username, password: password }),
      });
      if (!resp.ok) {
        loginErro.classList.remove("hidden");
        return;
      }
      const dado = await resp.json();
      await iniciarPainel(dado.username);
    } catch (e) {
      loginErro.classList.remove("hidden");
    } finally {
      loginBtn.disabled = false;
    }
  });

  logoutBtn.addEventListener("click", async function () {
    try {
      await apiFetch("/logout", { method: "POST" });
    } catch (e) {
      // apiFetch ja mostra o login em caso de 401
    }
    mostrarLogin();
  });

  // Ao carregar a pagina, tenta reaproveitar uma sessao ja valida (cookie httponly)
  // antes de exigir login de novo -- evita pedir senha a cada F5.
  (async function init() {
    try {
      const resp = await fetch(API + "/me", { credentials: "same-origin" });
      if (resp.ok) {
        const dado = await resp.json();
        await iniciarPainel(dado.username);
        return;
      }
    } catch (e) {
      // segue pro login normal
    }
    mostrarLogin();
  })();
})();
