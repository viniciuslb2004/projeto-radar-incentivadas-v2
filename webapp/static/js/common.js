// Utilidades compartilhadas: filtros, formatacao, tabs, modal de drill-down.

const AZUL_TONS = ["#223850", "#2E4A68", "#36587E", "#5878A0", "#7C93AC", "#A9BAC9", "#D3DCE3"];

// Escapa texto vindo da API antes de interpolar em innerHTML/template (texto E
// atributos). null/undefined -> "".
function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// URL externa segura pra href: so http(s)://, ja escapada; senao "#".
function escUrl(u) {
  const s = String(u || "").trim();
  return /^https?:\/\//i.test(s) ? esc(s) : "#";
}

// Mensagem padrao de erro amigavel (sem detalhe tecnico).
const MSG_ERRO_CARGA = "Não foi possível carregar os dados agora. Tente novamente em instantes.";
function htmlErroCarga(msg) {
  return `<p class="empty-state">${esc(msg || MSG_ERRO_CARGA)}</p>`;
}

function fmtBRL(v) {
  if (v === null || v === undefined || isNaN(v)) return "-";
  if (Math.abs(v) >= 1e9) return "R$ " + (v / 1e9).toFixed(1).replace(".", ",") + " bi";
  if (Math.abs(v) >= 1e6) return "R$ " + (v / 1e6).toFixed(1).replace(".", ",") + " mi";
  if (Math.abs(v) >= 1e3) return "R$ " + (v / 1e3).toFixed(0) + " mil";
  return "R$ " + Math.round(v);
}

function fmtBRLFull(v) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

function fmtNum(v) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR");
}

// Quando o frontend e o backend estao hospedados em dominios separados (ex:
// frontend na Vercel, backend no Render), API_BASE_URL (definida em config.js)
// aponta pro backend; localmente fica "" (mesma origem, como sempre).
function _urlCompleta(url) {
  if (url.startsWith("/api/") && window.API_BASE_URL) {
    return window.API_BASE_URL.replace(/\/$/, "") + url;
  }
  return url;
}

// /api/filtros e pedido tanto pelo filterbar compartilhado
// (common.js::_initFiltersAndTabsImpl) quanto pelos selects proprios da Busca
// (busca.js::_popularFiltrosBusca) -- mesmo endpoint, mesma resposta (so a
// Busca le alguns campos extras dela, ex: produtos/portes/subsetores). Sem
// cache, isso batia a rede DUAS VEZES em todo carregamento de pagina (os dois
// listeners de DOMContentLoaded disparam quase juntos) -- redundante, sem
// nenhum ganho de "dado mais fresco" (a resposta nao muda dentro de uma
// sessao). Cacheado pela PROMISE (nao so o valor resolvido) pra as duas
// chamadas concorrentes da carga inicial dividirem o MESMO fetch em voo, nao
// so evitar um fetch depois que o primeiro ja terminou. Uma falha de rede NAO
// fica cacheada (senao um erro passageiro do Aiven travaria os filtros pro
// resto da sessao), a proxima chamada tenta de novo.
let _filtrosCompartilhadosPromise = null;
function _fetchFiltrosCompartilhado() {
  if (!_filtrosCompartilhadosPromise) {
    _filtrosCompartilhadosPromise = fetchJSON("/api/filtros").catch((e) => {
      _filtrosCompartilhadosPromise = null;
      throw e;
    });
  }
  return _filtrosCompartilhadosPromise;
}

// Sem ISSO por padrao, uma chamada sem timeoutMs explicito nunca resolvia nem
// rejeitava se o backend travasse/nao respondesse (ex: cold-start do free tier do
// Render meio truncado por algum motivo) -- o await ficava pendurado pra sempre.
// Isso ja travou a pagina inteira de verdade: initFiltersAndTabs() (ver mais
// abaixo) so registra os cliques das abas DEPOIS do fetch de /api/status, entao um
// fetch sem timeout que nunca resolve deixa ate a NAVEGACAO entre abas travada,
// nao so o dado que ficaria faltando. 45s cobre com folga o cold-start do Render;
// chamadas que legitimamente demoram mais ja passam o proprio timeoutMs mais longo
// explicitamente, entao nao sao afetadas.
const TIMEOUT_PADRAO_MS = 45000;

// Area interna da Equipe Artica (/interno-artica, ver CLAUDE.md) -- MESMA SPA do
// site publico, so troca qual overlay de login aparece (ver _mostrarLanding
// abaixo, e a checagem proativa de staff em initFiltersAndTabs) e liga/desliga o
// botao "Quero saber mais" (so publico). As 3 funcionalidades extras (Salvar/
// Notas/Exportar Excel) sao controladas pelo flag `staff` de /api/me
// (obterSessaoAtual abaixo), NAO por este path -- uma conta de staff continua
// "staff" mesmo navegando pelas URLs publicas (/consolidado etc, mesma sessao/
// cookie compartilhado), entao os botoes internos aparecem em qualquer aba pra
// quem logou como staff, nao so' em /interno-artica.
const MODO_INTERNO = window.location.pathname.startsWith("/interno-artica");

// Sessao atual completa ({username, nome, staff}, de /api/me) -- cacheada numa
// Promise unica -- varios lugares da SPA (topbar, historico pessoal de busca,
// botoes da area interna) precisam saber "quem esta logado" e nao devem disparar
// um /api/me por chamador.
let _sessaoAtualPromise = null;
function obterSessaoAtual() {
  if (!_sessaoAtualPromise) {
    _sessaoAtualPromise = fetch(_urlCompleta("/api/me"), { credentials: "include" })
      .then((r) => (r.ok ? r.json() : { username: null, nome: null, staff: false }))
      .catch(() => ({ username: null, nome: null, staff: false }));
  }
  return _sessaoAtualPromise;
}

// "Quero saber mais" -- SEMPRE visivel pra quem nao e' staff (identificado ou
// nao: e' o proprio CTA que abre o modal de identificacao pra quem ainda nao se
// identificou, ver _completarIdentificacaoEregistrarInteresse mais abaixo), nunca
// pra sessao de staff (area interna tem seu proprio indicativo, "Modo interno" +
// botoes de Salvar/Notas/Exportar). Extraida pra funcao propria (era so um
// `.then` inline no DOMContentLoaded) pra poder ser chamada de novo depois de um
// opt-in bem-sucedido -- sem isso, a topbar (badge "Modo interno") ficaria com a
// leitura ANTIGA de /api/me pelo resto da visita, ja que _sessaoAtualPromise so
// busca uma vez (ver invalidacao em _completarIdentificacaoEregistrarInteresse).
function _atualizarTopbarSessao() {
  obterSessaoAtual().then((sessao) => {
    if (!sessao.staff) {
      document.getElementById("topbar-cta-grupo").classList.remove("hidden");
    }
    // "Modo interno" (indicacao visual discreta, pedido explicito do escopo de
    // /interno-artica) + botao de exportar operacoes salvas -- SO' pra sessao de
    // staff, em QUALQUER aba (a mesma sessao/cookie vale nas URLs publicas
    // tambem, ver MODO_INTERNO acima).
    if (sessao.staff) {
      document.getElementById("topbar-interno-badge").classList.remove("hidden");
      document.getElementById("topbar-exportar-salvos-btn").classList.remove("hidden");
    }
  });
}

// Username logado (ou null) -- mantido por compatibilidade dos chamadores
// existentes (busca.js, log de navegacao) que so precisam do username, nunca do
// flag `staff`.
function obterUsuarioAtual() {
  return obterSessaoAtual().then((sessao) => sessao.username || null);
}

// ============ Identificacao passwordless (ver #landing-overlay em index.html)
// ============
// Ate 2026-09-22: login por usuario+senha (contas individuais, `admin_usuarios`),
// depois identificacao passwordless por e-mail OBRIGATORIA (barreira de entrada,
// nada carregava sem sessao). Revertido em 2026-09-23 (pedido explicito do
// usuario, ver CLAUDE.md): a navegacao publica NAO exige mais identificacao --
// #landing-overlay virou um modal sob demanda (ver _mostrarLanding abaixo),
// aberto so pelo clique em "Quero saber mais". O cookie de sessao e httponly (JS
// nunca le/escreve ele diretamente) e enviado automaticamente pelo navegador via
// `credentials: "include"`.
class ErroAutenticacao extends Error {}

// Mostra o overlay de identificacao/login apropriado -- SO chamada hoje em dois
// casos (ver _falhaComoErro mais abaixo, unica chamadora vinda de fetchJSON/
// postJSON): (1) MODO_INTERNO sem sessao de staff (gate real de /interno-artica,
// ver tambem a checagem proativa em initFiltersAndTabs) e (2) POST /api/interesse
// devolvendo 401 (sessao expirou entre o clique em "Quero saber mais" e o envio
// do formulario -- caso raro, mas cobre o usuario ficando preso num formulario
// que nunca vai completar o opt-in). NUNCA mais chamada so por causa de uma rota
// de LEITURA de dado publico falhar (essas nao dependem mais de sessao nenhuma --
// ver secao "Acesso" em webapp/main.py) -- um erro nelas vira uma falha comum
// (`Error`, nao `ErroAutenticacao`), tratada pelo catch de cada chamador (a
// maioria ja deixa a secao vazia/mostra "não foi possível conectar", nunca deveria
// forcar quem so estava navegando anonimamente a se identificar por causa de um
// bug ou instabilidade passageira do backend). Idempotente -- seguro chamar
// varias vezes.
function _mostrarLanding(mensagemErro) {
  // /interno-artica mostra o login de STAFF (usuario+senha) -- NUNCA o modal de
  // identificacao publica (essa e' so pro site principal). Os dois overlays sao
  // mutuamente exclusivos (nunca os dois "hidden"=false ao mesmo tempo) -- ver
  // #landing-overlay/#landing-interno-overlay em index.html.
  if (MODO_INTERNO) {
    document.getElementById("landing-interno-overlay").classList.remove("hidden");
    const erro = document.getElementById("interno-login-erro");
    if (mensagemErro) {
      erro.textContent = mensagemErro;
      erro.classList.remove("hidden");
    } else {
      erro.classList.add("hidden");
    }
    const usuarioInput = document.getElementById("interno-login-usuario");
    if (usuarioInput) usuarioInput.focus();
    return;
  }
  document.getElementById("landing-overlay").classList.remove("hidden");
  document.getElementById("cadastro-form").classList.add("hidden");
  document.getElementById("identificar-form").classList.remove("hidden");
  const erro = document.getElementById("identificar-erro");
  if (mensagemErro) {
    erro.textContent = mensagemErro;
    erro.classList.remove("hidden");
  } else {
    erro.classList.add("hidden");
  }
  const emailInput = document.getElementById("identificar-email");
  if (emailInput) emailInput.focus();
}

// Decide o que fazer com uma resposta HTTP nao-ok de fetchJSON/postJSON: so os
// dois casos documentados em _mostrarLanding acima (MODO_INTERNO sem sessao de
// staff, ou 401 especificamente em POST /api/interesse) mostram um overlay e
// viram ErroAutenticacao -- QUALQUER outra falha (rota publica com 500/502,
// timeout, erro de rede) vira um `Error` comum, deixado pro catch de cada
// chamador tratar como sempre tratou uma falha de rede (a maioria ja tem
// `catch (e) { data = []; }`/estado vazio, ver ex. em consolidado.js/editais.js --
// nunca deveria forcar quem so estava navegando anonimamente a se identificar por
// causa de uma instabilidade passageira do backend).
function _falhaComoErro(r, url) {
  if (r.status === 401 && (MODO_INTERNO || url === "/api/interesse")) {
    _mostrarLanding(url === "/api/interesse" ? "Sua sessão expirou. Identifique-se novamente para continuar." : undefined);
    return new ErroAutenticacao("nao autenticado");
  }
  return new Error(`Falha ao acessar ${url} (HTTP ${r.status})`);
}

async function fetchJSON(url, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  try {
    const r = await fetch(fullUrl, { signal: controller.signal, credentials: "include" });
    if (!r.ok) throw _falhaComoErro(r, url);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// POST generico (usado, por exemplo, para mandar ao servidor o vetor de embedding
// ja calculado no navegador, no modo hospedado -- ver embeddings-client.js -- e
// para POST /api/interesse, ver mais abaixo).
async function postJSON(url, body, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  try {
    const r = await fetch(fullUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "include",
      signal: controller.signal,
    });
    if (!r.ok) throw _falhaComoErro(r, url);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// Backstop: qualquer ErroAutenticacao que escape sem handler nenhum (ex: um
// `await fetchJSON(...)` novo que alguem esqueca de proteger no futuro) so evita
// o erro barulhento (nao tratado) no console -- o overlay certo ja foi mostrado
// em _falhaComoErro, no momento em que o erro foi lancado.
window.addEventListener("unhandledrejection", (ev) => {
  if (ev.reason instanceof ErroAutenticacao) {
    ev.preventDefault();
  }
});

// 1o passo: so e-mail. "Ja usado nos ultimos 3 meses" -> acesso imediato (backend
// ja cria a sessao e devolve o cookie); senao -> pede os dados completos (2o
// passo, formulario #cadastro-form).
async function _identificarEmail(email) {
  try {
    const r = await fetch(_urlCompleta("/api/identificar"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
      credentials: "include",
    });
    const dado = await r.json().catch(() => ({}));
    if (r.status !== 200) {
      return { ok: false, mensagem: dado.detail || "Não foi possível continuar. Tente novamente." };
    }
    return { ok: true, precisaDados: !!dado.precisa_dados };
  } catch (e) {
    return { ok: false, mensagem: "Erro de rede -- tente novamente." };
  }
}

// 2o passo (e-mail novo OU ultimo acesso ha mais de 3 meses): nome/empresa/cargo.
// Sem senha em nenhum caso -- acesso concedido na hora, sem aprovacao de admin.
async function _cadastrarLead(dados) {
  try {
    const r = await fetch(_urlCompleta("/api/cadastrar"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
      credentials: "include",
    });
    const dado = await r.json().catch(() => ({}));
    if (r.status !== 200) {
      return { ok: false, mensagem: dado.detail || "Não foi possível concluir seu acesso." };
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, mensagem: "Erro de rede -- tente novamente." };
  }
}

// ============ Opt-in pos-identificacao ("Quero saber mais") ============
// Ate 2026-09-22, sucesso em /api/identificar ou /api/cadastrar precisava recarregar
// a plataforma inteira (location.reload() ou, na versao seguinte, um "entrar sem
// reload" que refazia manualmente o fetch de cada aba) porque a pagina nao tinha
// NENHUM dado carregado ate a identificacao acontecer (barreira de entrada). Isso
// nao existe mais: Consolidado/Insights/Linhas Incentivadas/Busca/Potenciais
// Linhas/Editais ja carregaram seus dados (publicos, sem sessao nenhuma) muito
// antes de alguem clicar em "Quero saber mais" -- entao completar a identificacao
// aqui so precisa (1) fechar o modal, (2) atualizar a topbar (ela cacheia /api/me
// numa Promise unica, ver obterSessaoAtual/_sessaoAtualPromise -- sem invalidar
// aqui, ficaria mostrando "nao identificado" pelo resto da visita) e (3) registrar
// o "quero saber mais" de verdade (POST /api/interesse, o proprio gatilho do
// opt-in) -- nunca precisa re-buscar nenhum dado de aba nem recarregar a pagina.
// Tipo do CTA clicado ("contato" = Quero Contatar | "relatorio" = Quero receber o
// relatorio) -- mesmo fluxo/modal, so muda o texto e o `tipo` enviado (o backend
// valida contra whitelist e grava um evento diferente, ver webapp/main.py).
let _tipoInteresse = "contato";
const _TEXTOS_INTERESSE = {
  contato: {
    titulo: "Obrigado pelo interesse!",
    texto: "Nosso time entrará em contato com você.",
    landing: "Quero Contatar",
  },
  relatorio: {
    titulo: "Pedido recebido!",
    texto: "Você receberá o relatório no seu e-mail.",
    landing: "Quero receber o relatório",
  },
};

function _mostrarAgradecimento() {
  const t = _TEXTOS_INTERESSE[_tipoInteresse] || _TEXTOS_INTERESSE.contato;
  document.getElementById("interesse-modal-titulo").textContent = t.titulo;
  document.getElementById("interesse-modal-texto").textContent = t.texto;
  document.getElementById("interesse-modal-overlay").classList.remove("hidden");
  document.getElementById("interesse-modal-fechar").focus();
}

async function _completarIdentificacaoEregistrarInteresse() {
  _sessaoAtualPromise = null;
  _atualizarTopbarSessao();
  document.getElementById("landing-overlay").classList.add("hidden");
  _mostrarAgradecimento();
  try {
    await postJSON("/api/interesse", { tipo: _tipoInteresse });
  } catch (e) {
    // best-effort -- o modal de agradecimento ja apareceu, uma falha de rede
    // aqui nao deve incomodar quem ja completou o formulario.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("landing-fechar-btn").addEventListener("click", () => {
    // Fecha sem nenhum efeito colateral -- a pessoa so volta pra tela/filtro onde
    // estava, exatamente como quem nunca clicou em "Quero saber mais" (o dado ja
    // estava carregado por baixo do modal o tempo todo).
    document.getElementById("landing-overlay").classList.add("hidden");
  });

  document.getElementById("identificar-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("identificar-btn");
    const erroEl = document.getElementById("identificar-erro");
    erroEl.classList.add("hidden");
    const email = document.getElementById("identificar-email").value.trim();
    if (!email) {
      erroEl.textContent = "Informe seu e-mail.";
      erroEl.classList.remove("hidden");
      return;
    }
    btn.disabled = true;
    btn.textContent = "Verificando...";
    const resultado = await _identificarEmail(email);
    btn.disabled = false;
    btn.textContent = "Continuar";
    if (!resultado.ok) {
      erroEl.textContent = resultado.mensagem;
      erroEl.classList.remove("hidden");
      return;
    }
    if (!resultado.precisaDados) {
      // E-mail ja conhecido e usado recentemente -- acesso concedido, sessao ja
      // criada pelo backend.
      await _completarIdentificacaoEregistrarInteresse();
      return;
    }
    // E-mail novo OU ultimo acesso ha mais de 3 meses -- pede os dados completos.
    document.getElementById("cadastro-email").value = email;
    document.getElementById("identificar-form").classList.add("hidden");
    document.getElementById("cadastro-form").classList.remove("hidden");
    document.getElementById("cadastro-nome").focus();
  });

  document.getElementById("cadastro-voltar-btn").addEventListener("click", () => {
    document.getElementById("cadastro-form").classList.add("hidden");
    document.getElementById("identificar-form").classList.remove("hidden");
    document.getElementById("identificar-email").focus();
  });

  document.getElementById("cadastro-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("cadastro-btn");
    const erroEl = document.getElementById("cadastro-erro");
    erroEl.classList.add("hidden");
    const dados = {
      nome: document.getElementById("cadastro-nome").value.trim(),
      empresa: document.getElementById("cadastro-empresa").value.trim(),
      cargo: document.getElementById("cadastro-cargo").value.trim(),
      email: document.getElementById("cadastro-email").value.trim(),
    };
    if (!dados.nome || !dados.empresa || !dados.cargo || !dados.email) {
      erroEl.textContent = "Preencha todos os campos.";
      erroEl.classList.remove("hidden");
      return;
    }
    btn.disabled = true;
    btn.textContent = "Enviando...";
    const resultado = await _cadastrarLead(dados);
    btn.disabled = false;
    btn.textContent = "Acessar plataforma";
    if (!resultado.ok) {
      erroEl.textContent = resultado.mensagem;
      erroEl.classList.remove("hidden");
      return;
    }
    await _completarIdentificacaoEregistrarInteresse();
  });

  _atualizarTopbarSessao();

  async function _cliqueCta(ev) {
    _tipoInteresse = ev.currentTarget.dataset.tipo === "relatorio" ? "relatorio" : "contato";
    const sessao = await obterSessaoAtual();
    if (sessao.username && !sessao.staff) {
      // Ja identificado num opt-in anterior -- registra de novo sem pedir os
      // dados de novo (mesmo comportamento de sempre pra quem ja se identificou).
      _mostrarAgradecimento();
      try {
        await postJSON("/api/interesse", { tipo: _tipoInteresse });
      } catch (e) {
        // best-effort -- ver comentario acima.
      }
      return;
    }
    // Visitante anonimo -- abre o modal de identificacao (reaproveita
    // #landing-overlay); so ao completar o formulario e' que o interesse de fato
    // e' registrado (ver _completarIdentificacaoEregistrarInteresse acima).
    document.getElementById("landing-acesso-titulo").textContent =
      (_TEXTOS_INTERESSE[_tipoInteresse] || _TEXTOS_INTERESSE.contato).landing;
    _mostrarLanding();
  }
  document.getElementById("topbar-interesse-btn").addEventListener("click", _cliqueCta);
  document.getElementById("topbar-relatorio-btn").addEventListener("click", _cliqueCta);
  document.getElementById("interesse-modal-fechar").addEventListener("click", () => {
    document.getElementById("interesse-modal-overlay").classList.add("hidden");
  });
});

// ============ Area interna da Equipe Artica (/interno-artica) ============
// Login de staff (usuario+senha, ver webapp/main.py::interno_login) -- reload
// completo em caso de sucesso, mesmo padrao do login/identificacao publica acima.
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("interno-login-form");
  if (!form) return; // defensivo -- este form so existe em index.html
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("interno-login-btn");
    const erroEl = document.getElementById("interno-login-erro");
    erroEl.classList.add("hidden");
    const username = document.getElementById("interno-login-usuario").value.trim();
    const password = document.getElementById("interno-login-senha").value;
    if (!username || !password) {
      erroEl.textContent = "Informe usuário e senha.";
      erroEl.classList.remove("hidden");
      return;
    }
    btn.disabled = true;
    btn.textContent = "Entrando...";
    try {
      const r = await fetch(_urlCompleta("/api/interno/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
        credentials: "include",
      });
      const dado = await r.json().catch(() => ({}));
      if (r.status !== 200) {
        erroEl.textContent = dado.detail || "Usuário ou senha incorretos.";
        erroEl.classList.remove("hidden");
        btn.disabled = false;
        btn.textContent = "Entrar";
        return;
      }
      location.reload();
    } catch (e2) {
      erroEl.textContent = "Erro de rede -- tente novamente.";
      erroEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Entrar";
    }
  });

  // "Exportar salvos" (Exportar Excel, item 3 do pedido de /interno-artica) --
  // baixa o .xlsx das operacoes salvas por ESTA conta de staff (ver
  // webapp/salvos.py/exportar_excel.py). POST sem body -- backend identifica o
  // usuario pela sessao (Depends(exigir_staff), nunca por parametro do cliente).
  document.getElementById("topbar-exportar-salvos-btn").addEventListener("click", async () => {
    await _baixarArquivoPost("/api/salvos/exportar", {}, "operacoes-salvas.xlsx");
  });
});

// Helper generico: POST que devolve um arquivo (blob) -- dispara o download do
// navegador. Usado por "Exportar salvos" (acima) e "Exportar Excel" da Busca
// (busca.js) -- os dois so' existem pra sessao de staff (gate real e' o backend,
// Depends(exigir_staff); aqui e' so' a mecanica de baixar o blob).
async function _baixarArquivoPost(url, body, nomeArquivoFallback) {
  let r;
  try {
    r = await fetch(_urlCompleta(url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      credentials: "include",
    });
  } catch (e) {
    alert("Não foi possível gerar o arquivo. Verifique sua conexão e tente novamente.");
    return;
  }
  if (!r.ok) {
    alert("Não foi possível gerar o arquivo. Tente novamente.");
    return;
  }
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(cd);
  const nomeArquivo = (match && match[1]) || nomeArquivoFallback;
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = nomeArquivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(blobUrl);
}

const MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

function currentFilters() {
  const filters = {
    agencia: document.getElementById("f-agencia").value,
    setor: document.getElementById("f-setor").value,
    subsetor: document.getElementById("f-subsetor").value,
    uf: document.getElementById("f-uf").value,
  };
  // Classificacao nativa BNDES (so com agencia=BNDES) e agente financeiro (so com
  // agencia=FINEP) -- fora desses casos nem vao pra query (backend tambem ignora).
  if (filters.agencia === "BNDES" && document.getElementById("f-classificacao").value === "nativo") {
    filters.classificacao = "nativo";
  }
  if (filters.agencia === "FINEP") {
    filters.agente = document.getElementById("f-agente").value;
  }

  const mesIni = document.getElementById("f-mes-ini").value;
  const anoIni = document.getElementById("f-ano-ini").value;
  if (mesIni && anoIni) {
    filters.data_inicio = `${anoIni}-${String(mesIni).padStart(2, "0")}-01`;
  }

  const mesFim = document.getElementById("f-mes-fim").value;
  const anoFim = document.getElementById("f-ano-fim").value;
  if (mesFim && anoFim) {
    let m = parseInt(mesFim, 10) + 1;
    let y = parseInt(anoFim, 10);
    if (m > 12) { m = 1; y += 1; }
    filters.data_fim = `${y}-${String(m).padStart(2, "0")}-01`;
  }

  return filters;
}

function qs(params) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "Todas" && v !== "Todos") p.set(k, v);
  });
  return p.toString();
}

const FILTER_LISTENERS = [];
function onFiltersChange(fn) { FILTER_LISTENERS.push(fn); }
// Devolve uma Promise que resolve quando TODOS os listeners (refreshConsolidado/
// refreshTendencias, ambos async) terminarem -- a maioria das chamadas (troca de
// filtro normal) ignora o retorno, dispara e esquece.
function notifyFiltersChange() {
  const f = currentFilters();
  return Promise.all(FILTER_LISTENERS.map((fn) => fn(f)));
}

// ============ Filtros na URL (query string) ============
// Cada aba reflete os PROPRIOS filtros na query string (nunca o path, que ja
// codifica qual aba esta aberta -- ver secao de roteamento logo abaixo), pra dar
// pra compartilhar um link que abre a mesma aba com os mesmos filtros aplicados.
// Usa SEMPRE replaceState (nunca pushState) pra nao poluir o historico de
// voltar/avancar do navegador a cada filtro alterado -- so a troca de ABA deve
// criar uma entrada de historico nova (ver _ativarView). Decisao deliberada e
// CONSERVADORA sobre o que entra na URL: so filtros que restringem QUAL FATIA dos
// dados aparece (setor, UF, agencia, data, texto de busca etc.). Qualquer coisa
// que so muda COMO os mesmos dados sao exibidos (granularidade do grafico de
// serie temporal -- ver #serie-granularidade, ja excluida explicitamente antes
// por pedido do usuario -- e tambem os selects de ORDENACAO em Editais/Linhas/
// Busca/modal de operacoes, e a pagina atual da paginacao de Linhas Incentivadas)
// fica de fora, tratada como estado local da pagina (mesmo padrao ja usado pra
// granularidade). Ambiguidade real: dava pra argumentar que ordenacao/pagina
// tambem deveriam entrar agora que a URL passou a carregar filtro -- decisao
// tomada foi NAO incluir (nenhum desses foi pedido explicitamente pra entrar na
// URL), pra manter escopo minimo e consistente com a exclusao ja definida da
// granularidade.
function paramsDaURL() {
  return new URLSearchParams(window.location.search);
}

// Cada aba lembra seu PROPRIO ultimo conjunto de filtros (nao herda de outra
// aba) -- mas Consolidado e Tendencias compartilham o mesmo #filterbar (mesmos
// elementos DOM fisicos, so escondido via display:none), entao sao tratados
// como um unico "grupo" (`painel`) pra esse fim: alternar entre os dois nunca
// deve limpar nada, ja que o filtro de um E o do outro (mesmo input). Busca,
// Editais e Linhas Incentivadas sao cada um o proprio grupo (filtros/conceitos
// de UI incompativeis entre si -- ex: Busca usa "regiao", Consolidado usa "uf").
// `_ultimaQueryPorGrupo` e um cache em memoria (nao sobrevive a um F5 de
// proposito -- um F5/link direto usa a query string ja presente na URL, ver
// `_aplicarFiltros*DaURL` de cada aba) que guarda, por grupo, a ultima query
// string sincronizada -- consultado por `_ativarView` (secao de roteamento
// abaixo) na hora de montar a URL de destino de um clique real numa aba. So
// precisa mexer na URL: os CAMPOS de filtro de cada aba ja preservam seu valor
// sozinhos ao trocar de aba (nenhum codigo os reseta quando a aba fica
// escondida), so a URL que ficava dessincronizada da tela.
const _ultimaQueryPorGrupo = {};
function _grupoDaView(view) {
  if (view === "consolidado" || view === "tendencias") return "painel";
  return view;
}
function _chaveCacheGrupo(view) {
  return _grupoDaView(view);
}

// Guarda qual aba esta ativa AGORA -- usado so pra `sincronizarFiltrosNaURL`
// saber em qual grupo gravar o cache acima (nao dá pra inferir isso so pelos
// `params` recebidos, que variam de aba pra aba).
let _viewAtivaAgora = null;

function sincronizarFiltrosNaURL(params) {
  const query = qs(params);
  const destino = window.location.pathname + (query ? "?" + query : "");
  if (destino !== window.location.pathname + window.location.search) {
    window.history.replaceState(window.history.state, "", destino);
  }
  if (_viewAtivaAgora) _ultimaQueryPorGrupo[_chaveCacheGrupo(_viewAtivaAgora)] = query;
}

// ============ Link direto pra uma operação (deep link do modal de detalhe) ============
// Pedido do usuário: clicar numa transação (ex: "Ver operações deste setor" dentro de
// uma Linha Incentivada -> lista -> uma operação, mas vale pra QUALQUER lugar que abre
// openOperacaoDetalhe -- Busca, tabela de maiores operações, grupo econômico etc, já que
// todos passam pelo MESMO modal) deve gerar um link que, colado por qualquer pessoa
// (logada), abre direto no detalhe daquela operação -- sem precisar navegar/buscar de novo.
// Guarda o id num parâmetro de query PRÓPRIO (`operacao`), preservando o resto da URL
// (path da aba + filtros já ativos) em vez de reescrever tudo como
// `sincronizarFiltrosNaURL` faz -- o modal é um OVERLAY por cima de qualquer aba, não uma
// troca de view, então não faz sentido ele mexer no path/filtros da aba de baixo.
function _idOperacaoDaURL() {
  return paramsDaURL().get("operacao");
}

function _definirOperacaoNaURL(id) {
  const params = paramsDaURL();
  if (id) params.set("operacao", id);
  else params.delete("operacao");
  const query = params.toString();
  const destino = window.location.pathname + (query ? "?" + query : "");
  if (destino !== window.location.pathname + window.location.search) {
    window.history.replaceState(window.history.state, "", destino);
  }
}

// Debounce generico -- usado pelos campos de texto livre (query da Busca, texto da
// Editais, busca de Linhas Incentivadas) pra nao chamar sincronizarFiltrosNaURL a
// cada tecla digitada. O VALOR final ainda fica refletido na URL assim que o
// usuario para de digitar (`ms` depois da ultima tecla).
function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// Roteamento por caminho: a URL reflete qual aba esta aberta (/consolidado,
// /tendencias, /busca, /editais, /linhas-incentivadas) via PATH -- os filtros de
// cada aba (ver secao acima) vao na query string do mesmo caminho.
const _SLUG_PARA_VIEW = {
  "": "consolidado",
  "consolidado": "consolidado",
  "tendencias": "tendencias",
  "busca": "busca",
  "editais": "editais",
  "linhas-incentivadas": "linhas",
  "potenciais-linhas": "potenciais",
};
const _VIEW_PARA_SLUG = {
  consolidado: "consolidado",
  tendencias: "tendencias",
  busca: "busca",
  editais: "editais",
  linhas: "linhas-incentivadas",
  potenciais: "potenciais-linhas",
};

function _viewInicialDaURL() {
  const slug = window.location.pathname.replace(/^\/+|\/+$/g, "");
  return _SLUG_PARA_VIEW[slug] || "consolidado";
}

function _ativarView(view, empilharHistorico) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  document.getElementById("filterbar").style.display =
    view === "busca" || view === "editais" || view === "linhas" || view === "potenciais" ? "none" : "flex";
  const caminho = "/" + (_VIEW_PARA_SLUG[view] || "consolidado");
  const mudouDeAba = window.location.pathname !== caminho;
  if (empilharHistorico) {
    // Clique numa aba: so cria uma entrada de historico nova se REALMENTE mudou
    // de aba (clicar na aba ja ativa nao deve limpar filtro nenhum). Ao mudar de
    // verdade, restaura o ULTIMO conjunto de filtros que o GRUPO da aba de
    // destino teve nesta mesma visita a pagina (`_ultimaQueryPorGrupo`) -- nunca
    // herda o da aba de ORIGEM, que pode ser de um grupo diferente (ver
    // `_grupoDaView`). Os campos de filtro em si nao precisam de nada aqui: ja
    // preservam seu valor sozinhos (nenhum reset ao trocar de aba), so a URL
    // que precisava voltar a bater com o que ja esta na tela.
    if (mudouDeAba) {
      const query = _ultimaQueryPorGrupo[_chaveCacheGrupo(view)] || "";
      window.history.pushState({ view }, "", caminho + (query ? "?" + query : ""));
    }
  } else if (mudouDeAba) {
    // Estado inicial (carregamento direto/F5) ou popstate (voltar/avancar):
    // preserva a query string como estava -- pode ser um link compartilhado com
    // filtros, ou uma entrada de historico anterior que ja tinha os seus.
    window.history.replaceState({ view }, "", caminho + window.location.search);
  }
  // Semeia o cache pro grupo desta aba a partir da URL atual, se ainda nao
  // tiver nada gravado -- cobre o caso de carregar a pagina direto (F5/link
  // compartilhado) numa aba com filtro na URL: sem isso, o cache so passaria a
  // existir depois da PRIMEIRA mudanca de filtro feita pelo usuario, entao
  // sair e voltar pra essa aba antes disso perderia a query que ja estava la.
  const chaveGrupo = _chaveCacheGrupo(view);
  if (_ultimaQueryPorGrupo[chaveGrupo] === undefined) {
    _ultimaQueryPorGrupo[chaveGrupo] = window.location.search.replace(/^\?/, "");
  }
  // Log de navegacao (V2 do log de acessos, ver CLAUDE.md) -- so quando ha alguem
  // LOGADO (obterUsuarioAtual ja cacheia isso numa Promise, nao dispara /api/me de
  // novo) e so numa troca de aba DE VERDADE (mudouDeAba), pra nao duplicar evento
  // reativando a mesma aba. Fire-and-forget: nunca atrasa nem trava a troca de aba
  // (a UI ja trocou de view antes desta linha rodar), erro de rede e so ignorado.
  if (mudouDeAba) {
    obterUsuarioAtual().then((usuario) => {
      if (!usuario) return;
      fetch(_urlCompleta("/api/eventos/navegacao"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aba: view }),
        credentials: "include",
      }).catch(() => {});
    });
  }
  _viewAtivaAgora = view;
}

// Nao deixa o usuario chegar num intervalo invertido (De > Ate): sempre que um dos 4
// selects de data muda, compara os dois pares como "ano*12+mes" (comparavel direto,
// sem precisar montar Date) -- se o par que NAO acabou de mudar ficou invalido em
// relacao ao que mudou, ajusta ele pra igualar o que o usuario acabou de escolher
// (em vez de reverter a escolha do usuario ou so avisar sem corrigir). O aviso
// inline (#filtro-data-aviso, mesmo padrao visual de .confianca-baixa-aviso usado na
// busca) aparece por alguns segundos so quando uma correcao de verdade acontece.
function _ordemMesAno(mes, ano) {
  if (!mes || !ano) return null;
  return parseInt(ano, 10) * 12 + parseInt(mes, 10);
}

function validarIntervaloDatas(campoAlterado) {
  const mesIniEl = document.getElementById("f-mes-ini");
  const anoIniEl = document.getElementById("f-ano-ini");
  const mesFimEl = document.getElementById("f-mes-fim");
  const anoFimEl = document.getElementById("f-ano-fim");

  const ordemIni = _ordemMesAno(mesIniEl.value, anoIniEl.value);
  const ordemFim = _ordemMesAno(mesFimEl.value, anoFimEl.value);
  if (ordemIni === null || ordemFim === null || ordemIni <= ordemFim) return;

  // O campo que acabou de mudar manda -- o outro lado e que se ajusta pra igualar.
  const alterouInicio = campoAlterado === "f-mes-ini" || campoAlterado === "f-ano-ini";
  if (alterouInicio) {
    mesFimEl.value = mesIniEl.value;
    anoFimEl.value = anoIniEl.value;
  } else {
    mesIniEl.value = mesFimEl.value;
    anoIniEl.value = anoFimEl.value;
  }

  const aviso = document.getElementById("filtro-data-aviso");
  if (aviso) {
    aviso.style.display = "block";
    clearTimeout(aviso._timeoutId);
    aviso._timeoutId = setTimeout(() => { aviso.style.display = "none"; }, 4000);
  }
}

// Liga/desliga os degrades de borda de `.tabs-wrap` (ver style.css) conforme
// da pra rolar `.tabs` pra esquerda/direita NAQUELE momento -- a barra de
// scroll nativa foi escondida de proposito (feia em larguras de desktop
// intermediarias), entao esse e o unico aviso visual de que ha mais abas fora
// da tela. Chamada no carregamento, ao redimensionar a janela e a cada scroll
// dentro de `.tabs` (arrastar/roda do mouse muda quanto da pra rolar em cada
// direcao).
function _atualizarSombraAbas() {
  const wrap = document.getElementById("tabs-wrap");
  const tabs = document.getElementById("tabs");
  if (!wrap || !tabs) return;
  const folgaDireita = tabs.scrollWidth - tabs.clientWidth - tabs.scrollLeft;
  wrap.classList.toggle("tem-mais-a-esquerda", tabs.scrollLeft > 2);
  wrap.classList.toggle("tem-mais-a-direita", folgaDireita > 2);
}

function _ligarBotoesDeAba() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => _ativarView(btn.dataset.view, true));
  });

  window.addEventListener("popstate", () => {
    _ativarView(_viewInicialDaURL(), false);
  });
  _ativarView(_viewInicialDaURL(), false);

  const tabsEl = document.getElementById("tabs");
  if (tabsEl) tabsEl.addEventListener("scroll", _atualizarSombraAbas);
  window.addEventListener("resize", _atualizarSombraAbas);
  _atualizarSombraAbas();
}

// Esconde a tela de carregamento inicial -- chamada em TODO caminho de saida de
// initFiltersAndTabs() (sucesso ou erro), pra nunca deixar o usuario preso atras
// dela se o backend estiver fora do ar.
function _esconderLoadingOverlay() {
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.classList.add("hidden");
}

// Tendencias.js precisa dos valores do filterbar compartilhado (agencia/setor/
// UF/data, incluindo os que vieram de um link com filtro na URL -- ver
// initFiltersAndTabs abaixo) ja aplicados ANTES do seu proprio fetch inicial,
// mas quem chama initFiltersAndTabs() e so consolidado.js. Em vez de um
// setTimeout arbitrario torcendo pra initFiltersAndTabs() (que depende de
// /api/status + /api/filtros por rede) terminar a tempo -- flaky de verdade
// contra o Aiven free tier (ver CLAUDE.md) e que ja mostrou na pratica buscar
// com os filtros ainda default/vazios quando a rede demora mais que o palpite
// -- tendencias.js AGUARDA esta promise, resolvida no finally de
// initFiltersAndTabs() (sucesso ou erro, pra nunca travar esperando pra sempre).
let _resolverFiltrosProntos;
const filtrosProntosPromise = new Promise((resolve) => { _resolverFiltrosProntos = resolve; });

async function initFiltersAndTabs() {
  // Link direto pra uma operacao (ver _definirOperacaoNaURL/openOperacaoDetalhe) --
  // capturado AGORA, antes de qualquer coisa que mexa na URL (_ligarBotoesDeAba/
  // _ativarView), senao um F5 numa aba cuja _aplicarFiltros*DaURL reescreve a
  // query string via sincronizarFiltrosNaURL perderia o parametro antes de eu
  // conseguir ler. O modal so abre DEPOIS que aba/filtros estiverem
  // resolvidos (ver abaixo) -- puramente estetico (nao trava se o backend cair no
  // meio, mesmo espirito do _resolverFiltrosProntos no finally).
  const idOperacaoDaURL = _idOperacaoDaURL();

  // Troca de aba e 100% client-side (so classes CSS) -- liga ISSO primeiro e
  // incondicionalmente, antes de qualquer fetch, pra a navegacao nunca depender
  // do backend responder.
  _ligarBotoesDeAba();

  // Gate de STAFF pra /interno-artica -- desde a reversao da barreira de entrada
  // (2026-09-23) a maioria das rotas /api/* NAO 401 mais por falta de sessao (ver
  // secao "Acesso" em webapp/main.py), entao nao da mais pra depender de um 401
  // incidental do primeiro fetch (como o codigo antigo dependia) pra acionar este
  // gate -- checa /api/me DIRETO e proativamente, ANTES de qualquer fetch de
  // dado, e bloqueia a tela se a sessao atual nao for de staff. O dado em si
  // (fetches de _initFiltersAndTabsImpl abaixo) e' publico e carregaria
  // normalmente mesmo sem isso -- so nao deve aparecer pro visitante ate a tela
  // desbloquear, exatamente como o gate de staff sempre se comportou aqui.
  if (MODO_INTERNO) {
    const sessao = await obterSessaoAtual();
    if (!sessao.staff) {
      _mostrarLanding();
      _esconderLoadingOverlay();
      _resolverFiltrosProntos();
      return;
    }
  }

  try {
    await _initFiltersAndTabsImpl();
  } finally {
    _resolverFiltrosProntos();
  }

  if (idOperacaoDaURL) openOperacaoDetalhe(idOperacaoDaURL);
}

async function _initFiltersAndTabsImpl() {
  const pill = document.getElementById("status-pill");
  // /api/status e /api/filtros sao independentes (nenhum usa o resultado do
  // outro) mas eram esperados em SEQUENCIA -- medido ao vivo (relatorio de
  // performance 2026-09-22): cada round trip de rede custa ~180-400ms contra o
  // Aiven, entao 2 chamadas sequenciais no caminho critico pos-login custavam o
  // dobro do necessario. Disparando os dois fetches JUNTOS aqui (chamar
  // _fetchFiltrosCompartilhado() so inicia o fetch e devolve a promise
  // cacheada, ver definicao acima) -- o tratamento de erro de cada um continua
  // exatamente como antes, cada await abaixo so espera a resposta que ja esta
  // a caminho.
  const filtrosPromise = _fetchFiltrosCompartilhado();

  let status;
  try {
    status = await fetchJSON("/api/status");
  } catch (e) {
    // /api/status e' publica (ver secao "Acesso" em webapp/main.py) -- nao 401
    // mais por falta de sessao, entao qualquer erro aqui e' rede/backend de
    // verdade (ErroAutenticacao so viria de MODO_INTERNO, ja tratado acima antes
    // de chegar aqui).
    _esconderLoadingOverlay();
    pill.textContent = "não foi possível conectar ao servidor";
    return;
  }
  window.MODO_HOSPEDADO = !!status.hospedado;
  window.BUSCA_IA_ATIVA = !!status.busca_ia_ativa;
  document.dispatchEvent(new CustomEvent("modo-hospedado-conhecido"));
  // Pedido do usuario (2026-09-11): so a contagem, sem "atualizado em ..." --
  // o dado de ultimo_refresh continua vindo de /api/status (usado em outros
  // lugares, ex: painel de admin), so parou de aparecer aqui.
  pill.textContent = `${fmtNum(status.n_operacoes)} operações`;

  let filtros;
  try {
    filtros = await filtrosPromise;
  } catch (e) {
    _esconderLoadingOverlay();
    return;
  }
  _popularFiltrosCompartilhados(filtros);

  // Link compartilhado / F5: se a URL ja tem filtros (so relevante quando a aba
  // ativa e Consolidado ou Tendencias, que sao as duas que usam este filterbar
  // compartilhado -- ver _viewInicialDaURL), sobrescreve os valores padrao ACIMA
  // ANTES do primeiro fetch de cada aba (consolidado.js/tendencias.js so leem os
  // valores via currentFilters() depois que initFiltersAndTabs() retorna).
  const viewAtiva = _viewInicialDaURL();
  if (viewAtiva === "consolidado" || viewAtiva === "tendencias") {
    const paramsIniciais = paramsDaURL();
    if (paramsIniciais.has("agencia")) document.getElementById("f-agencia").value = paramsIniciais.get("agencia");
    if (paramsIniciais.has("setor")) document.getElementById("f-setor").value = paramsIniciais.get("setor");
    // Restaura o valor bruto -- a lista de opcoes de #f-subsetor ainda esta com o
    // conjunto COMPLETO neste ponto (so restrita ao setor escolhido depois, ver
    // _repopularSubsetorCascata em consolidado.js, chamada logo apos
    // initFiltersAndTabs()), entao o valor de um link salvo sempre existe como opcao.
    if (paramsIniciais.has("subsetor")) document.getElementById("f-subsetor").value = paramsIniciais.get("subsetor");
    if (paramsIniciais.has("uf")) document.getElementById("f-uf").value = paramsIniciais.get("uf");
    if (paramsIniciais.has("classificacao")) document.getElementById("f-classificacao").value = paramsIniciais.get("classificacao");
    if (paramsIniciais.has("agente")) document.getElementById("f-agente").value = paramsIniciais.get("agente");
    if (paramsIniciais.has("mes_ini")) document.getElementById("f-mes-ini").value = paramsIniciais.get("mes_ini");
    if (paramsIniciais.has("ano_ini")) document.getElementById("f-ano-ini").value = paramsIniciais.get("ano_ini");
    if (paramsIniciais.has("mes_fim")) document.getElementById("f-mes-fim").value = paramsIniciais.get("mes_fim");
    if (paramsIniciais.has("ano_fim")) document.getElementById("f-ano-fim").value = paramsIniciais.get("ano_fim");
    // Um link salvo/antigo pode trazer um mes_fim/ano_fim alem do teto real da base
    // (ver _aplicarTetoMesFim acima) -- reaplica o teto ja aqui, antes do primeiro
    // fetch de cada aba, pra nunca aplicar um filtro "fim" alem do dado disponivel.
    _aplicarTetoMesFim();
  }

  _atualizarFiltrosPorAgencia();
  const CAMPOS_DATA = ["f-mes-ini", "f-ano-ini", "f-mes-fim", "f-ano-fim"];
  ["f-agencia", "f-classificacao", "f-agente", "f-setor", "f-subsetor", "f-uf", ...CAMPOS_DATA].forEach((id) => {
    document.getElementById(id).addEventListener("change", async () => {
      if (id === "f-agencia") _atualizarFiltrosPorAgencia();
      // Teto dinamico (item 5): #f-ano-fim mudar pode tornar meses ja desabilitados
      // validos de novo (ano anterior ao mais recente) ou invalidar o mes atual (ano
      // mais recente da base) -- reaplica ANTES de validarIntervaloDatas, que compara
      // #f-mes-fim/#f-ano-fim ja coerentes com o teto.
      if (id === "f-ano-fim") _aplicarTetoMesFim();
      if (CAMPOS_DATA.includes(id)) validarIntervaloDatas(id);
      // Cascata Setor -> Subsetor (ver consolidado.js::_repopularSubsetorCascata):
      // quando o Setor muda, o Subsetor precisa ser repopulado/resetado ANTES do
      // notifyFiltersChange logo abaixo, senao os graficos disparariam por uma
      // fracao de segundo com um subsetor incompativel com o novo setor. Hook
      // opcional (definido em consolidado.js) pra nao hardcodar logica de
      // subsetor aqui -- common.js so sabe que "algo pode precisar reagir antes".
      if (id === "f-setor" && typeof window.aoMudarSetorFiltro === "function") {
        await window.aoMudarSetorFiltro();
      }
      notifyFiltersChange();
      _sincronizarFiltrosCompartilhadosNaURL();
    });
  });

  _esconderLoadingOverlay();
}

// Remove todas as <option> de um select alem da 1a (o "Todas"/"Todos" fixo ja
// escrito no HTML) -- evita duplicar opcao se este select for repopulado de novo.
function _limparOpcoesExtras(sel) {
  while (sel.options.length > 1) sel.remove(1);
}

function _preencherSelectFiltro(id, values) {
  const sel = document.getElementById(id);
  _limparOpcoesExtras(sel);
  (values || []).forEach((v) => sel.appendChild(new Option(v, v)));
}

// Teto dinamico do filtro de periodo (item 5 do pedido de melhorias, 2026-09-23):
// {ano, mes} do ULTIMO mes com dado real em operations.data_contratacao (ver
// filtros.data_max, /api/filtros -- MAX(data_contratacao) calculado no banco a
// cada chamada, nunca hardcoded aqui). Antes disso #f-mes-fim sempre oferecia os
// 12 meses do ano escolhido em #f-ano-fim, mesmo quando o ano mais recente da
// base (#f-ano-fim so lista anos com pelo menos 1 operacao, ver `anos` abaixo)
// so tinha dado ate um mes especifico -- ex: base com dado ate Jun/2026 deixava
// escolher Dez/2026, um recorte que nunca devolveria a operacao nenhuma alem das
// ja existentes ate Jun. `_aplicarTetoMesFim` (abaixo) desabilita as opcoes de
// mes POSTERIORES ao ultimo real, so quando o ano escolhido em #f-ano-fim e' o
// ano mais recente da base (anos anteriores tem o ano inteiro coberto).
let _dataMaxDisponivel = null;

function _aplicarTetoMesFim() {
  const anoFimEl = document.getElementById("f-ano-fim");
  const mesFimEl = document.getElementById("f-mes-fim");
  if (!anoFimEl || !mesFimEl || !_dataMaxDisponivel) return;
  const anoFimSelecionado = Number(anoFimEl.value);
  const ehAnoMaisRecente = anoFimSelecionado === _dataMaxDisponivel.ano;
  Array.from(mesFimEl.options).forEach((opt) => {
    opt.disabled = ehAnoMaisRecente && Number(opt.value) > _dataMaxDisponivel.mes;
  });
  if (ehAnoMaisRecente && Number(mesFimEl.value) > _dataMaxDisponivel.mes) {
    mesFimEl.value = _dataMaxDisponivel.mes;
  }
}

// Selects de ano (sem opcao fixa no HTML, ver index.html -- <select
// id="f-ano-ini"></select> vazio) sao sempre RECRIADOS do zero; os de MES
// (Jan..Dez) so populam uma vez (guardado pelo proprio `options.length`).
function _preencherAnosEMeses(filtros) {
  const anos = (filtros.anos || []).filter((a) => a !== null).sort((a, b) => a - b);
  const anoIni = document.getElementById("f-ano-ini");
  const anoFim = document.getElementById("f-ano-fim");
  anoIni.innerHTML = "";
  anoFim.innerHTML = "";
  anos.forEach((a) => {
    anoIni.appendChild(new Option(a, a));
    anoFim.appendChild(new Option(a, a));
  });

  const mesIni = document.getElementById("f-mes-ini");
  const mesFim = document.getElementById("f-mes-fim");
  if (!mesIni.options.length) {
    MESES.forEach((nome, i) => {
      mesIni.appendChild(new Option(nome, i + 1));
      mesFim.appendChild(new Option(nome, i + 1));
    });
  }

  const dataMin = filtros.data_min ? new Date(filtros.data_min) : null;
  const dataMax = filtros.data_max ? new Date(filtros.data_max) : null;
  _dataMaxDisponivel = dataMax ? { ano: dataMax.getUTCFullYear(), mes: dataMax.getUTCMonth() + 1 } : null;
  if (dataMin) {
    mesIni.value = dataMin.getUTCMonth() + 1;
    anoIni.value = dataMin.getUTCFullYear();
  } else if (anos.length) {
    anoIni.value = anos[0];
  }
  if (dataMax) {
    mesFim.value = dataMax.getUTCMonth() + 1;
    anoFim.value = dataMax.getUTCFullYear();
  } else if (anos.length) {
    anoFim.value = anos[anos.length - 1];
  }
  _aplicarTetoMesFim();
}

// Popula o filterbar compartilhado (Consolidado/Tendencias) a partir da
// resposta de /api/filtros -- extraido da carga inicial pra nao duplicar
// listener nenhum (os `addEventListener` de change continuam so em
// _initFiltersAndTabsImpl, que roda uma unica vez por carregamento de pagina).
// Mostra "Classificacao setorial" so com agencia=BNDES e "Agente financeiro" so com
// agencia=FINEP (filtros discretos, dependentes da agencia).
function _atualizarFiltrosPorAgencia() {
  const agencia = document.getElementById("f-agencia").value;
  document.getElementById("f-classificacao-wrap").style.display = agencia === "BNDES" ? "" : "none";
  document.getElementById("f-agente-wrap").style.display = agencia === "FINEP" ? "" : "none";
}

function _popularFiltrosCompartilhados(filtros) {
  _preencherSelectFiltro("f-agencia", filtros.agencias);
  _preencherSelectFiltro("f-agente", (filtros.agentes_finep || []).filter(Boolean));
  _preencherSelectFiltro("f-setor", (filtros.setores || []).filter(Boolean));
  // Populacao inicial de #f-subsetor com a lista COMPLETA (todos os subsetores, de
  // qualquer setor) -- narrada pra so os do setor escolhido em consolidado.js
  // (_repopularSubsetorCascata), chamada logo apos initFiltersAndTabs() retornar.
  _preencherSelectFiltro("f-subsetor", (filtros.subsetores || []).filter(Boolean));
  _preencherSelectFiltro("f-uf", (filtros.ufs || []).filter(Boolean));
  _preencherAnosEMeses(filtros);
}

// Filtros compartilhados por Consolidado e Tendencias (mesmo filterbar, ver
// #filterbar em index.html) -- granularidade do grafico de serie temporal
// (#serie-granularidade, fica dentro da secao visual do Consolidado) fica DE
// FORA de proposito, pedido explicito e anterior do usuario (ver "Filtros na
// URL" acima).
function _sincronizarFiltrosCompartilhadosNaURL() {
  const params = {
    agencia: document.getElementById("f-agencia").value,
    setor: document.getElementById("f-setor").value,
    subsetor: document.getElementById("f-subsetor").value,
    uf: document.getElementById("f-uf").value,
    classificacao: currentFilters().classificacao,
    agente: currentFilters().agente,
    mes_ini: document.getElementById("f-mes-ini").value,
    ano_ini: document.getElementById("f-ano-ini").value,
    mes_fim: document.getElementById("f-mes-fim").value,
    ano_fim: document.getElementById("f-ano-fim").value,
  };
  // Seletores proprios de Tendencias (drill-down por setor) -- ver tendencias.js.
  if (_viewAtivaAgora === "tendencias" && typeof window.filtrosExtrasTendenciasURL === "function") {
    Object.assign(params, window.filtrosExtrasTendenciasURL());
  }
  sincronizarFiltrosNaURL(params);
}

// ============ Modal de drill-down ============
const modalOverlay = () => document.getElementById("modal-overlay");

function closeModal() {
  modalOverlay().classList.remove("open");
  // Limpa o `?operacao=<id>` (ver openOperacaoDetalhe) -- so existe enquanto o
  // modal de detalhe esta aberto; openOperacoesModal (lista) nunca grava esse
  // parametro, entao fechar o modal de lista tambem so limpa se por acaso
  // houvesse um -- no-op inofensivo nesse caso.
  _definirOperacaoNaURL(null);
}

let modalExtraFilters = {};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("modal-close").addEventListener("click", closeModal);
  modalOverlay().addEventListener("click", (e) => {
    if (e.target === modalOverlay()) closeModal();
  });
  // Esc fecha o modal aberto (interesse tem prioridade, fica por cima).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const interesse = document.getElementById("interesse-modal-overlay");
    if (interesse && !interesse.classList.contains("hidden")) interesse.classList.add("hidden");
    else if (modalOverlay().classList.contains("open")) closeModal();
  });
  document.getElementById("modal-ordenar").addEventListener("change", () => {
    openOperacoesModal(document.getElementById("modal-title").textContent, modalExtraFilters, true);
  });
});

async function openOperacoesModal(title, extraFilters, manterOrdenacao) {
  if (!manterOrdenacao) modalExtraFilters = extraFilters || {};
  document.getElementById("modal-title").textContent = title;
  const body = document.getElementById("modal-body");
  const ordenarSelect = document.getElementById("modal-ordenar");
  ordenarSelect.style.display = "inline-block";
  document.getElementById("modal-copiar-link-btn").style.display = "none";
  document.getElementById("modal-favoritar-btn").classList.add("hidden");
  document.getElementById("modal-nota-container").classList.add("hidden");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const [order_by, order_dir] = ordenarSelect.value.split("-");
  const params = Object.assign(currentFilters(), modalExtraFilters, { order_by, order_dir });
  const token = (openOperacoesModal._token = (openOperacoesModal._token || 0) + 1);
  let ops;
  try {
    ops = await fetchJSON("/api/operacoes" + "?" + qs(params) + "&limit=300");
  } catch (e) {
    if (token === openOperacoesModal._token) body.innerHTML = htmlErroCarga();
    return;
  }
  if (token !== openOperacoesModal._token) return;

  if (!Array.isArray(ops) || !ops.length) {
    body.innerHTML = '<p class="empty-state">Nenhuma operação encontrada para esse filtro.</p>';
    return;
  }

  body.innerHTML = _renderTabelaOperacoesAgrupada(ops);

  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
  _ligarGruposOperacoes(body);
}

// ============ Agrupamento de transacoes consecutivas da mesma empresa ============
// Pedido (Insights, item 12.1): no detalhamento de operacoes (este modal, aberto ao
// clicar num setor/subsetor/segmento/UF/porte/"Destinacao dos Recursos"), quando a
// MESMA empresa aparece em linhas CONSECUTIVAS (depende da ordenacao escolhida em
// #modal-ordenar -- ex: "Cliente (A-Z)" tende a agrupar, "Maior valor" so por
// coincidencia), agrupa visualmente sob um cabecalho clicavel com um resumo (qtd de
// operacoes + volume total); clique expande/recolhe. NUNCA reordena os dados (a
// ordenacao ja escolhida e respeitada tal como veio da API) -- so detecta sequencias
// JA adjacentes, uma empresa com 2 operacoes nao-consecutivas (outra empresa no meio)
// vira 2 "grupos" de 1 linha cada, sem forcar nada. Agrupa por CNPJ (mais confiavel
// que o nome) com fallback pro nome do cliente quando o CNPJ nao esta disponivel.
function _renderTabelaOperacoesAgrupada(ops) {
  const grupos = [];
  ops.forEach((op) => {
    const chave = op.cnpj || op.cliente || "";
    const ultimo = grupos[grupos.length - 1];
    if (chave && ultimo && ultimo.chave === chave) {
      ultimo.ops.push(op);
    } else {
      grupos.push({ chave, cliente: op.cliente, ops: [op] });
    }
  });

  const linhaOperacao = (op, atributosExtra) => `<tr data-id="${esc(op.id)}" ${atributosExtra || ""}>
      <td>${esc(op.cliente || "-")}</td>
      <td>${esc(op.agencia || "-")}</td>
      <td>${esc(op.uf || "-")}</td>
      <td>${esc(op.setor_bndes || "Não classificado")}</td>
      <td>${esc(op.data_contratacao || "-")}</td>
      <td>${fmtBRLFull(op.valor_contratado)}</td>
    </tr>`;

  let html = '<table class="ops-table"><thead><tr>' +
    "<th>Cliente</th><th>Agência</th><th>UF</th><th>Setor</th><th>Data</th><th>Valor contratado</th>" +
    "</tr></thead><tbody>";
  grupos.forEach((g, i) => {
    if (g.ops.length === 1) {
      html += linhaOperacao(g.ops[0]);
      return;
    }
    const valorTotal = g.ops.reduce((acc, op) => acc + (op.valor_contratado || 0), 0);
    html += `<tr class="ops-grupo-header" data-grupo="${i}">
        <td colspan="6"><span class="ops-grupo-seta">▸</span> ${esc(g.cliente || "-")}
          <span class="ops-grupo-resumo">${g.ops.length} operações · ${fmtBRLFull(valorTotal)}</span></td>
      </tr>`;
    g.ops.forEach((op) => {
      html += linhaOperacao(op, `class="ops-grupo-item" data-grupo-item="${i}" style="display:none;"`);
    });
  });
  html += "</tbody></table>";
  return html;
}

function _ligarGruposOperacoes(body) {
  body.querySelectorAll("tr.ops-grupo-header").forEach((tr) => {
    tr.addEventListener("click", () => {
      const idx = tr.dataset.grupo;
      const aberto = tr.classList.toggle("aberto");
      const seta = tr.querySelector(".ops-grupo-seta");
      if (seta) seta.textContent = aberto ? "▾" : "▸";
      body.querySelectorAll(`tr[data-grupo-item="${idx}"]`).forEach((item) => {
        item.style.display = aberto ? "" : "none";
      });
    });
  });
}

function fmtCampoDetalhe(campo) {
  const v = campo.valor;
  switch (campo.tipo) {
    case "moeda":
      return fmtBRLFull(v);
    case "percentual":
      return `${Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
    case "meses":
      return `${v} meses`;
    case "dias":
      return `${v} dias`;
    case "data":
      return v;
    default:
      return String(v).trim();
  }
}

// Botao "Copiar link" do modal de detalhe de operacao -- so aparece em
// openOperacaoDetalhe (escondido de novo em openOperacoesModal/editais.js/
// linhas.js, que reusam o MESMO elemento). A URL ja foi atualizada com
// `?operacao=<id>` por _definirOperacaoNaURL ANTES desta funcao ser chamada
// (ver openOperacaoDetalhe) -- so precisa copiar `location.href` como esta
// na hora do clique, nunca reconstruir a URL aqui (evita duas fontes de verdade pro
// mesmo link). `navigator.clipboard` exige contexto seguro (https ou localhost) --
// sempre verdade em producao (Vercel) e em dev local (uvicorn em 127.0.0.1); sem
// fallback de `document.execCommand('copy')` porque esse caminho antigo esta
// deprecado e o navegador so bloquearia em cenarios (http:// nao-local) que este
// projeto nunca roda.
function _configurarBotaoCopiarLink(opId) {
  const btn = document.getElementById("modal-copiar-link-btn");
  if (!btn) return;
  btn.style.display = "inline-flex";
  const textoOriginal = "🔗 Copiar link";
  btn.textContent = textoOriginal;
  btn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      btn.textContent = "✓ Link copiado!";
    } catch (e) {
      btn.textContent = "Não foi possível copiar";
    } finally {
      setTimeout(() => { btn.textContent = textoOriginal; }, 2000);
    }
  };
}

// "Salvar" + Notas (area interna, /interno-artica) -- so aparece quando o backend
// devolveu "salva" no detalhe (GET /api/operacoes/{id}), o que so acontece pra
// sessao de STAFF (ver webapp/main.py::operacao_detalhe) -- pra qualquer outra
// sessao (ou nenhuma), data.salva e' `undefined` e este bloco so esconde os dois
// elementos, nunca chama a API de salvos (que devolveria 403 mesmo assim, mas nem
// vale a pena tentar). Gate de VERDADE continua sendo o backend
// (Depends(exigir_staff) em cada rota /api/salvos*) -- isto aqui e' so' UI.
function _configurarSalvarNotaInterna(opId, data) {
  const favBtn = document.getElementById("modal-favoritar-btn");
  const notaContainer = document.getElementById("modal-nota-container");
  const notaTexto = document.getElementById("modal-nota-texto");
  const notaStatus = document.getElementById("modal-nota-status");
  if (!favBtn || !notaContainer) return;
  if (data.salva === undefined) {
    favBtn.classList.add("hidden");
    notaContainer.classList.add("hidden");
    return;
  }

  let salva = !!data.salva;
  const atualizarVisual = () => {
    favBtn.classList.remove("hidden");
    favBtn.classList.toggle("ativo", salva);
    favBtn.textContent = salva ? "★ Salvo" : "☆ Salvar";
    notaContainer.classList.toggle("hidden", !salva);
  };
  notaTexto.value = data.nota || "";
  notaStatus.textContent = "";
  atualizarVisual();

  favBtn.onclick = async () => {
    favBtn.disabled = true;
    try {
      const r = salva
        ? await fetch(_urlCompleta(`/api/salvos/operacoes/${opId}`), { method: "DELETE", credentials: "include" })
        : await fetch(_urlCompleta(`/api/salvos/operacoes/${opId}`), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
            credentials: "include",
          });
      if (r.status === 401) { _mostrarLanding(); return; }
      if (!r.ok) throw new Error("falha ao salvar");
      salva = !salva;
      if (!salva) notaTexto.value = "";
      atualizarVisual();
    } catch (e) {
      alert("Não foi possível atualizar. Tente novamente.");
    } finally {
      favBtn.disabled = false;
    }
  };

  let notaTimer = null;
  notaTexto.oninput = () => {
    notaStatus.textContent = "Salvando...";
    clearTimeout(notaTimer);
    notaTimer = setTimeout(async () => {
      try {
        const r = await fetch(_urlCompleta(`/api/salvos/operacoes/${opId}`), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nota: notaTexto.value }),
          credentials: "include",
        });
        if (r.status === 401) { _mostrarLanding(); return; }
        notaStatus.textContent = r.ok ? "Nota salva." : "Não foi possível salvar a nota.";
      } catch (e) {
        notaStatus.textContent = "Erro de rede ao salvar a nota.";
      }
      setTimeout(() => { notaStatus.textContent = ""; }, 2000);
    }, 600);
  };
}

async function openOperacaoDetalhe(id) {
  document.getElementById("modal-title").textContent = "Detalhe da operação";
  document.getElementById("modal-ordenar").style.display = "none";
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  document.getElementById("modal-favoritar-btn").classList.add("hidden");
  document.getElementById("modal-nota-container").classList.add("hidden");
  modalOverlay().classList.add("open");
  // Reflete o id na URL (ver _definirOperacaoNaURL acima) ANTES do fetch --
  // mesmo se o id nao existir (`data.secoes` vazio abaixo), o link continua
  // reproduzindo o que o usuario estava vendo ("detalhe nao encontrado" e um
  // estado real, nao um motivo pra esconder o parametro).
  _definirOperacaoNaURL(id);
  _configurarBotaoCopiarLink(id);

  const token = (openOperacaoDetalhe._token = (openOperacaoDetalhe._token || 0) + 1);
  let data;
  try {
    data = await fetchJSON(`/api/operacoes/${encodeURIComponent(id)}`);
  } catch (e) {
    if (token === openOperacaoDetalhe._token) body.innerHTML = htmlErroCarga();
    return;
  }
  if (token !== openOperacaoDetalhe._token) return;
  if (!data || !data.secoes || !data.secoes.length) {
    body.innerHTML = '<p class="empty-state">Detalhe não encontrado.</p>';
    return;
  }
  _configurarSalvarNotaInterna(id, data);

  const badge = `<span class="badge" style="background:var(--blue-lightest); color:var(--navy); margin-left:8px;">${esc(data.agencia || data.instrumento || "")}${data.instrumento && data.agencia ? " · " + esc(data.instrumento) : ""}</span>`;
  document.getElementById("modal-title").innerHTML = `Detalhe da operação ${badge}`;

  let html = '<div class="detalhe-secoes">';
  data.secoes.forEach((secao) => {
    const textoLongo = secao.campos.find((c) => c.tipo === "texto_longo");
    const camposCurtos = secao.campos.filter((c) => c.tipo !== "texto_longo");

    html += `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">${esc(secao.titulo)}</div>`;

    if (camposCurtos.length) {
      html += '<div class="detalhe-grid">';
      camposCurtos.forEach((c) => {
        html += `<div class="detalhe-campo">
          <div class="detalhe-label">${esc(c.label)}</div>
          <div class="detalhe-valor">${esc(fmtCampoDetalhe(c))}</div>
        </div>`;
      });
      html += "</div>";
    }
    if (textoLongo) {
      html += `<div class="detalhe-texto-longo">${esc(fmtCampoDetalhe(textoLongo))}</div>`;
    }
    html += "</div>";
  });
  html += "</div>";
  body.innerHTML = html;

  // Integracao transacoes <-> linhas incentivadas (item 8): mesma logica do lado
  // inverso em linhas.js -- so setor_bndes (taxonomia nativa das 4 categorias),
  // rotulado "potencialmente compativel", nunca misturado com o detalhe da operacao.
  if (data.setor_bndes && typeof fetchJSON === "function") {
    try {
      const linhas = await fetchJSON("/api/linhas?" + qs({ setor: data.setor_bndes, limit: 3 }));
      if (linhas.resultados && linhas.resultados.length) {
        const div = document.createElement("div");
        div.className = "detalhe-secao";
        div.innerHTML = `<div class="detalhe-secao-titulo">Linhas incentivadas potencialmente compatíveis <span class="hint">mesmo setor -- não é confirmação de elegibilidade</span></div>` +
          '<ul class="clickable-list">' +
          linhas.resultados.map((l) => `<li data-linha-id="${esc(l.id)}"><span>${esc(l.nome_simplificado || l.nome_oficial)}</span><span class="badge neutro">${esc(l.instituicao)}</span></li>`).join("") +
          "</ul>";
        body.appendChild(div);
        div.querySelectorAll("li[data-linha-id]").forEach((li) => {
          li.addEventListener("click", () => {
            if (typeof openLinhaDetalhe === "function") openLinhaDetalhe(li.dataset.linhaId);
          });
        });
      }
    } catch (e) {
      // integracao e um extra -- se falhar, so nao mostra a secao.
    }
  }

  // Grupo economico (mesma raiz de CNPJ, matriz+filiais) -- mesmo padrao da secao de
  // linhas compativeis acima: carregada a parte, so aparece se houver resultado, nunca
  // bloqueia o resto do detalhe se falhar.
  try {
    const grupo = await fetchJSON(`/api/operacoes/${id}/grupo-economico`);
    if (grupo.resultados && grupo.resultados.length) {
      const div = document.createElement("div");
      div.className = "detalhe-secao";
      div.innerHTML = `<div class="detalhe-secao-titulo">Outras operações do mesmo grupo econômico (${grupo.resultados.length}) <span class="hint">mesma raiz de CNPJ</span></div>` +
        '<ul class="clickable-list">' +
        grupo.resultados.map((o) => `<li data-op-id="${esc(o.id)}"><span>${esc(o.cliente || "-")}</span><span class="badge neutro">${esc(o.agencia || "")} ·${fmtBRL(o.valor_contratado)}</span></li>`).join("") +
        "</ul>";
      body.appendChild(div);
      div.querySelectorAll("li[data-op-id]").forEach((li) => {
        li.addEventListener("click", () => openOperacaoDetalhe(li.dataset.opId));
      });
    }
  } catch (e) {
    // integracao e um extra -- se falhar, so nao mostra a secao.
  }
}
