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
  const pendentesTbody = document.getElementById("admin-pendentes-tbody");
  const acessosTbody = document.getElementById("admin-acessos-tbody");
  const cardsEl = document.getElementById("admin-cards");
  const novoUsuarioBtn = document.getElementById("admin-novo-usuario-btn");
  const novoUsuarioForm = document.getElementById("admin-novo-usuario-form");
  const novoUsuarioErro = document.getElementById("admin-novo-usuario-erro");
  const refreshOperacoesBtn = document.getElementById("admin-refresh-operacoes-btn");
  const refreshEditaisBtn = document.getElementById("admin-refresh-editais-btn");
  const enriquecerBtn = document.getElementById("admin-enriquecer-btn");
  const saudeCardsEl = document.getElementById("admin-saude-cards");
  const saudeTbody = document.getElementById("admin-saude-tbody");
  const correcaoBuscaInput = document.getElementById("admin-correcao-busca");
  const correcaoResultadosEl = document.getElementById("admin-correcao-resultados");
  const correcaoSelecionadaEl = document.getElementById("admin-correcao-selecionada");
  const correcaoCamposWrap = document.getElementById("admin-correcao-campos-wrap");
  const correcaoCampoSelect = document.getElementById("admin-correcao-campo");
  const correcaoValorInput = document.getElementById("admin-correcao-valor");
  const correcaoSalvarBtn = document.getElementById("admin-correcao-salvar-btn");
  const correcaoErroEl = document.getElementById("admin-correcao-erro");
  const correcoesTbody = document.getElementById("admin-correcoes-tbody");
  const usuarioModal = document.getElementById("admin-usuario-modal");
  const usuarioModalTitulo = document.getElementById("admin-usuario-modal-titulo");
  const usuarioModalResumo = document.getElementById("admin-usuario-modal-resumo");
  const usuarioModalTbody = document.getElementById("admin-usuario-modal-tbody");
  const usuarioModalFechar = document.getElementById("admin-usuario-modal-fechar");
  let operacaoSelecionada = null;

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
    if (!dashboard.github_actions_configurado) {
      [refreshOperacoesBtn, refreshEditaisBtn].forEach(function (btn) {
        btn.title = "GITHUB_ACTIONS_TOKEN nao configurado -- peca pro usuario criar o token e configurar na Vercel.";
      });
    }
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
      usuariosTbody.innerHTML = '<tr><td colspan="5">Nenhum usuário encontrado.</td></tr>';
      return;
    }
    usuariosTbody.innerHTML = usuarios
      .map(function (u) {
        const pillClasse = u.ativo ? "ativo" : "inativo";
        const pillTexto = u.ativo ? "Ativo" : "Inativo";
        const acaoTexto = u.ativo ? "Desativar" : "Ativar";
        const roleTexto = u.role === "admin" ? "Admin" : "Usuário";
        return `<tr>
          <td><button type="button" class="admin-usuario-link" data-id="${u.id}">${u.username}</button></td>
          <td><span class="admin-pill admin-role">${roleTexto}</span></td>
          <td><span class="admin-pill ${pillClasse}">${pillTexto}</span></td>
          <td>${formatarData(u.criado_em)}</td>
          <td>
            <button class="admin-toggle-btn" data-acao="ativo" data-id="${u.id}" data-ativo="${u.ativo}">${acaoTexto}</button>
            <button class="admin-toggle-btn" data-acao="excluir" data-id="${u.id}" data-username="${u.username}">Excluir</button>
          </td>
        </tr>`;
      })
      .join("");
  }

  async function carregarUsuarios(q) {
    const resp = await apiFetch("/usuarios?q=" + encodeURIComponent(q || ""));
    const dado = await resp.json();
    renderUsuarios(dado.usuarios);
  }

  function renderPendentes(pendentes) {
    if (!pendentes.length) {
      pendentesTbody.innerHTML = '<tr><td colspan="3">Nenhuma solicitação pendente.</td></tr>';
      return;
    }
    pendentesTbody.innerHTML = pendentes
      .map(
        (p) => `<tr>
          <td>${p.username}</td>
          <td>${formatarData(p.criado_em)}</td>
          <td>
            <button class="admin-toggle-btn" data-acao="aprovar" data-id="${p.id}">Aprovar</button>
            <button class="admin-toggle-btn" data-acao="rejeitar" data-id="${p.id}">Rejeitar</button>
          </td>
        </tr>`
      )
      .join("");
  }

  async function carregarPendentes() {
    const resp = await apiFetch("/usuarios/pendentes");
    const dado = await resp.json();
    renderPendentes(dado.pendentes);
  }

  pendentesTbody.addEventListener("click", async function (ev) {
    const btn = ev.target.closest(".admin-toggle-btn[data-acao]");
    if (!btn) return;
    btn.disabled = true;
    try {
      await apiFetch(`/usuarios/${btn.dataset.id}/${btn.dataset.acao}`, { method: "POST" });
      await Promise.all([carregarPendentes(), carregarUsuarios(buscaInput.value)]);
    } finally {
      btn.disabled = false;
    }
  });

  function renderAcessos(acessos) {
    if (!acessos.length) {
      acessosTbody.innerHTML = '<tr><td colspan="5">Nenhum acesso registrado ainda.</td></tr>';
      return;
    }
    acessosTbody.innerHTML = acessos
      .map(
        (a) => `<tr>
          <td>${a.username}</td>
          <td>${a.origem === "admin" ? "Painel admin" : "Site principal"}</td>
          <td>${a.evento === "login" ? "Login" : "Logout"}</td>
          <td>${a.ip || "--"}</td>
          <td>${formatarData(a.criado_em)}</td>
        </tr>`
      )
      .join("");
  }

  async function carregarAcessos() {
    const resp = await apiFetch("/acessos?limit=100");
    const dado = await resp.json();
    renderAcessos(dado.acessos);
  }

  usuariosTbody.addEventListener("click", async function (ev) {
    const btn = ev.target.closest(".admin-toggle-btn");
    if (!btn) return;
    const id = btn.dataset.id;
    btn.disabled = true;
    try {
      if (btn.dataset.acao === "ativo") {
        const ativoAtual = btn.dataset.ativo === "true";
        await apiFetch(`/usuarios/${id}/ativo`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ativo: !ativoAtual }),
        });
      } else if (btn.dataset.acao === "excluir") {
        if (!confirm(`Excluir o usuário "${btn.dataset.username}" definitivamente? Essa ação não pode ser desfeita.`)) {
          btn.disabled = false;
          return;
        }
        const resp = await apiFetch(`/usuarios/${id}`, { method: "DELETE" });
        if (!resp.ok) {
          const erro = await resp.json();
          alert(erro.detail || "Não foi possível excluir este usuário.");
        }
      }
      await carregarUsuarios(buscaInput.value);
    } finally {
      btn.disabled = false;
    }
  });

  // Drill-down por usuario (pedido do usuario): clicar no nome abre um modal com o
  // historico de login/logout DAQUELA pessoa (reaproveita admin_acessos_log, so
  // filtra por usuario_id -- NAO e tracking de navegacao/clique, so login/logout).
  usuariosTbody.addEventListener("click", async function (ev) {
    const link = ev.target.closest(".admin-usuario-link[data-id]");
    if (!link) return;
    usuarioModalTitulo.textContent = "Carregando...";
    usuarioModalResumo.innerHTML = "";
    usuarioModalTbody.innerHTML = '<tr><td colspan="4">Carregando...</td></tr>';
    usuarioModal.classList.remove("hidden");
    const resp = await apiFetch(`/usuarios/${link.dataset.id}/acessos`);
    const dado = await resp.json();
    usuarioModalTitulo.textContent = dado.username;
    usuarioModalResumo.innerHTML = `
      <div class="admin-card"><div class="valor">${dado.total_logins}</div><div class="rotulo">Total de logins</div></div>
      <div class="admin-card"><div class="valor">${formatarData(dado.primeiro_acesso)}</div><div class="rotulo">Primeiro acesso</div></div>
      <div class="admin-card"><div class="valor">${formatarData(dado.ultimo_acesso)}</div><div class="rotulo">Último acesso</div></div>
    `;
    if (!dado.eventos.length) {
      usuarioModalTbody.innerHTML = '<tr><td colspan="4">Nenhum acesso registrado ainda.</td></tr>';
    } else {
      usuarioModalTbody.innerHTML = dado.eventos
        .map(
          (e) => `<tr>
            <td>${e.origem === "admin" ? "Painel admin" : "Site principal"}</td>
            <td>${e.evento === "login" ? "Login" : "Logout"}</td>
            <td>${e.ip || "--"}</td>
            <td>${formatarData(e.criado_em)}</td>
          </tr>`
        )
        .join("");
    }
  });

  usuarioModalFechar.addEventListener("click", function () {
    usuarioModal.classList.add("hidden");
  });
  usuarioModal.addEventListener("click", function (ev) {
    if (ev.target === usuarioModal) usuarioModal.classList.add("hidden");
  });

  novoUsuarioBtn.addEventListener("click", function () {
    novoUsuarioForm.classList.toggle("hidden");
  });

  novoUsuarioForm.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    novoUsuarioErro.classList.add("hidden");
    const username = document.getElementById("admin-novo-usuario-username").value.trim();
    const password = document.getElementById("admin-novo-usuario-senha").value;
    const role = document.getElementById("admin-novo-usuario-role").value;
    if (!username || !password) {
      novoUsuarioErro.textContent = "Usuário e senha são obrigatórios.";
      novoUsuarioErro.classList.remove("hidden");
      return;
    }
    try {
      const resp = await apiFetch("/usuarios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role }),
      });
      if (!resp.ok) {
        const erro = await resp.json();
        novoUsuarioErro.textContent = erro.detail || "Não foi possível criar o usuário.";
        novoUsuarioErro.classList.remove("hidden");
        return;
      }
      novoUsuarioForm.reset();
      novoUsuarioForm.classList.add("hidden");
      await carregarUsuarios(buscaInput.value);
    } catch (e) {
      novoUsuarioErro.textContent = "Não foi possível criar o usuário.";
      novoUsuarioErro.classList.remove("hidden");
    }
  });

  let buscaTimeout = null;
  buscaInput.addEventListener("input", function () {
    clearTimeout(buscaTimeout);
    buscaTimeout = setTimeout(function () {
      carregarUsuarios(buscaInput.value);
    }, 250);
  });

  async function dispararRefresh(btn, msgEl, path) {
    btn.disabled = true;
    msgEl.textContent = "Disparando...";
    msgEl.className = "admin-refresh-msg";
    try {
      const resp = await apiFetch(path, { method: "POST" });
      const dado = await resp.json();
      if (!resp.ok) {
        msgEl.textContent = dado.detail || "Não foi possível disparar.";
        msgEl.className = "admin-refresh-msg erro";
      } else {
        msgEl.textContent = dado.mensagem || "Disparado com sucesso.";
        msgEl.className = "admin-refresh-msg sucesso";
      }
    } catch (e) {
      msgEl.textContent = "Erro de rede ao disparar.";
      msgEl.className = "admin-refresh-msg erro";
    } finally {
      btn.disabled = false;
    }
  }

  refreshOperacoesBtn.addEventListener("click", function () {
    dispararRefresh(refreshOperacoesBtn, document.getElementById("admin-refresh-operacoes-msg"), "/refresh/operacoes");
  });
  refreshEditaisBtn.addEventListener("click", function () {
    dispararRefresh(refreshEditaisBtn, document.getElementById("admin-refresh-editais-msg"), "/refresh/editais");
  });

  enriquecerBtn.addEventListener("click", async function () {
    const msgEl = document.getElementById("admin-enriquecer-msg");
    enriquecerBtn.disabled = true;
    msgEl.textContent = "Processando lote (pode levar alguns segundos)...";
    msgEl.className = "admin-refresh-msg";
    try {
      const resp = await apiFetch("/enriquecer-pendentes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tamanho_lote: 20 }),
      });
      const dado = await resp.json();
      if (!resp.ok) {
        msgEl.textContent = dado.detail || "Não foi possível processar.";
        msgEl.className = "admin-refresh-msg erro";
      } else {
        msgEl.textContent = `Processados ${dado.processados}, resolvidos ${dado.resolvidos_cnpj_cnae}, reclassificados ${dado.operacoes_reclassificadas}. Restam ${dado.restantes} pendentes.`;
        msgEl.className = "admin-refresh-msg sucesso";
        await carregarDashboard();
      }
    } catch (e) {
      msgEl.textContent = "Erro de rede ao processar.";
      msgEl.className = "admin-refresh-msg erro";
    } finally {
      enriquecerBtn.disabled = false;
    }
  });

  // ============ Saude do banco (proxy) ============
  async function carregarSaudeBanco() {
    const resp = await apiFetch("/saude-banco");
    const dado = await resp.json();
    saudeCardsEl.innerHTML = `
      <div class="admin-card"><div class="valor">${dado.tamanho_logico_mb} MB</div><div class="rotulo">Tamanho lógico do banco</div></div>
      <div class="admin-card"><div class="valor">${dado.conexoes_abertas}</div><div class="rotulo">Conexões abertas agora</div></div>
    `;
    if (!dado.tabelas_por_bloat.length) {
      saudeTbody.innerHTML = '<tr><td colspan="5">Sem dados de estatísticas ainda.</td></tr>';
      return;
    }
    saudeTbody.innerHTML = dado.tabelas_por_bloat
      .map(
        (t) => `<tr>
          <td>${t.tabela}</td>
          <td>${fmtNumOuTraco(t.linhas_vivas)}</td>
          <td>${fmtNumOuTraco(t.linhas_mortas)}</td>
          <td>${formatarData(t.ultimo_vacuum)}</td>
          <td>${formatarData(t.ultimo_autovacuum)}</td>
        </tr>`
      )
      .join("");
  }

  function fmtNumOuTraco(v) {
    return v != null ? v : "--";
  }

  // ============ Correcoes manuais ============
  let buscaCorrecaoTimeout = null;
  // A lista de resultados fica ABERTA/VISIVEL o tempo todo que houver um termo de
  // busca (pedido do usuario) -- selecionar uma operacao pra editar nao fecha a
  // lista, pra poder corrigir varias operacoes da mesma busca em sequencia. Cada
  // resultado tem um icone de caneta que abre o formulario JA PREENCHIDO com o
  // valor atual do campo escolhido (setor_bndes por padrao).
  correcaoBuscaInput.addEventListener("input", function () {
    clearTimeout(buscaCorrecaoTimeout);
    const termo = correcaoBuscaInput.value.trim();
    if (!termo) {
      correcaoResultadosEl.classList.add("hidden");
      correcaoResultadosEl.innerHTML = "";
      return;
    }
    buscaCorrecaoTimeout = setTimeout(async function () {
      const resp = await apiFetch("/operacoes/buscar?q=" + encodeURIComponent(termo));
      const dado = await resp.json();
      if (!dado.operacoes.length) {
        correcaoResultadosEl.innerHTML = '<div class="admin-correcao-resultado-item">Nenhuma operação encontrada.</div>';
      } else {
        correcaoResultadosEl.innerHTML = dado.operacoes
          .map((o) => {
            const opJson = JSON.stringify(o).replace(/'/g, "&#39;");
            const selecionada = operacaoSelecionada && operacaoSelecionada.id === o.id;
            return `<div class="admin-correcao-resultado-item${selecionada ? " selecionada" : ""}">
              <span>#${o.id} — ${o.cliente || "(sem nome)"} — setor: ${o.setor_bndes || "--"} / ${o.subsetor_bndes || "--"} / ${o.segmento || "--"}</span>
              <button type="button" class="admin-correcao-editar-btn" title="Editar esta operação" data-op='${opJson}'>✏️</button>
            </div>`;
          })
          .join("");
      }
      correcaoResultadosEl.classList.remove("hidden");
    }, 250);
  });

  correcaoResultadosEl.addEventListener("click", function (ev) {
    const btn = ev.target.closest(".admin-correcao-editar-btn[data-op]");
    if (!btn) return;
    operacaoSelecionada = JSON.parse(btn.dataset.op);
    correcaoSelecionadaEl.textContent = `Editando: #${operacaoSelecionada.id} — ${operacaoSelecionada.cliente || "(sem nome)"}`;
    correcaoSelecionadaEl.classList.remove("hidden");
    correcaoCamposWrap.classList.remove("hidden");
    // Ja preenchido com o valor ATUAL do campo (padrao setor_bndes) -- o usuario
    // edita em cima em vez de comecar do zero.
    correcaoCampoSelect.value = "setor_bndes";
    correcaoValorInput.value = operacaoSelecionada.setor_bndes || "";
  });

  correcaoCampoSelect.addEventListener("change", function () {
    if (!operacaoSelecionada) return;
    correcaoValorInput.value = operacaoSelecionada[correcaoCampoSelect.value] || "";
  });

  correcaoSalvarBtn.addEventListener("click", async function () {
    correcaoErroEl.classList.add("hidden");
    if (!operacaoSelecionada) return;
    const valorNovo = correcaoValorInput.value.trim();
    if (!valorNovo) {
      correcaoErroEl.textContent = "Informe o novo valor.";
      correcaoErroEl.classList.remove("hidden");
      return;
    }
    correcaoSalvarBtn.disabled = true;
    try {
      const resp = await apiFetch("/correcoes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: operacaoSelecionada.id,
          campo: correcaoCampoSelect.value,
          valor_novo: valorNovo,
        }),
      });
      const dado = await resp.json();
      if (!resp.ok) {
        correcaoErroEl.textContent = dado.detail || "Não foi possível salvar.";
        correcaoErroEl.classList.remove("hidden");
        return;
      }
      correcaoValorInput.value = "";
      correcaoCamposWrap.classList.add("hidden");
      correcaoSelecionadaEl.classList.add("hidden");
      operacaoSelecionada = null;
      await carregarCorrecoes();
    } finally {
      correcaoSalvarBtn.disabled = false;
    }
  });

  function renderCorrecoes(correcoes) {
    if (!correcoes.length) {
      correcoesTbody.innerHTML = '<tr><td colspan="8">Nenhuma correção registrada ainda.</td></tr>';
      return;
    }
    correcoesTbody.innerHTML = correcoes
      .map(
        (c) => `<tr>
          <td>#${c.operation_id} — ${c.cliente || "(sem nome)"}</td>
          <td>${c.campo}</td>
          <td>${c.valor_anterior || "--"}</td>
          <td>${c.valor_novo}</td>
          <td>${c.usuario || "--"}</td>
          <td>${formatarData(c.criado_em)}</td>
          <td><span class="admin-pill ${c.ativa ? "ativo" : "inativo"}">${c.ativa ? "Ativa" : "Inativa"}</span></td>
          <td>${c.ativa ? `<button class="admin-toggle-btn" data-id="${c.id}">Desativar</button>` : ""}</td>
        </tr>`
      )
      .join("");
  }

  async function carregarCorrecoes() {
    const resp = await apiFetch("/correcoes?limit=50");
    const dado = await resp.json();
    renderCorrecoes(dado.correcoes);
  }

  correcoesTbody.addEventListener("click", async function (ev) {
    const btn = ev.target.closest(".admin-toggle-btn");
    if (!btn) return;
    btn.disabled = true;
    try {
      await apiFetch(`/correcoes/${btn.dataset.id}/desativar`, { method: "POST" });
      await carregarCorrecoes();
    } finally {
      btn.disabled = false;
    }
  });

  async function iniciarPainel(username) {
    usuarioLogadoEl.textContent = username;
    mostrarPainel();
    await Promise.all([
      carregarDashboard(),
      carregarUsuarios(""),
      carregarPendentes(),
      carregarAcessos(),
      carregarSaudeBanco(),
      carregarCorrecoes(),
    ]);
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
